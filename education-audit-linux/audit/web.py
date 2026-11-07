import csv
import hmac
import io
import json
import os
import secrets
from collections import Counter
from datetime import timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, session, abort, flash, Response, g
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .models import Organization, Run, Result, Page, utcnow
from .network import normalize_url, validate_public, FetchError
from .rules import KINDS, STATUSES, PRIORITIES
from .worker import enqueue
from .ai import public_state, test_connection

RUN_STATUSES = {'queued': 'В очереди', 'running': 'Проверяется', 'completed': 'Завершено', 'failed': 'Не удалось проверить'}

def totals(run):
    values = Counter(r.status for r in run.results if r.review != 'dismissed') if run else Counter()
    count = sum(v for k,v in values.items() if k != 'na')
    return {'pass': values['pass'], 'problems': values['error']+values['warning'], 'unknown': values['unknown'],
            'total': count, 'coverage': round((count-values['unknown'])/count*100) if count else 0}

def create_app(factory, engine):
    app = Flask(__name__)
    secret = os.getenv('SECRET_KEY', '')
    if not secret or secret.startswith('CHANGE_ME'):
        raise RuntimeError('Run python configure.py and set SECRET_KEY in .env.')
    app.config.update(SECRET_KEY=secret, MAX_CONTENT_LENGTH=1_000_000,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')

    @app.before_request
    def before_request():
        g.db = factory()
        if request.method == 'POST':
            supplied = request.form.get('csrf_token', '')
            expected = session.get('csrf_token', '')
            if not supplied or not expected or not hmac.compare_digest(supplied, expected):
                abort(400, 'Сессия формы истекла. Обновите страницу и повторите действие.')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.teardown_request
    def teardown(exc):
        db = g.pop('db', None)
        if db:
            db.close()

    def csrf():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        return session['csrf_token']

    @app.template_filter('localtime')
    def localtime(value):
        if value is None:
            return '—'
        return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Magadan')).strftime('%d.%m.%Y %H:%M')

    @app.context_processor
    def globals_():
        state=public_state()
        return dict(csrf_token=csrf, kinds=KINDS, statuses=STATUSES, priorities=PRIORITIES,
                    run_statuses=RUN_STATUSES, totals=totals, ai_enabled=state['enabled'],ai_state=state)

    @app.route('/ai',methods=['GET','POST'])
    def ai_settings():
        result=test_connection() if request.method=='POST' else None
        return render_template('ai_settings.html',active='ai',connection=result)

    def get_org(oid):
        org = g.db.get(Organization, oid)
        if not org:
            abort(404)
        return org

    def get_run(rid):
        run = g.db.get(Run, rid)
        if not run:
            abort(404)
        return run

    def latest_map():
        last = select(func.max(Run.id)).group_by(Run.org_id)
        return {r.org_id: r for r in g.db.scalars(select(Run).where(Run.id.in_(last)))}

    @app.get('/health')
    def health():
        try:
            g.db.execute(text('SELECT 1'))
            return {'status': 'ok', 'database': engine.dialect.name}
        except SQLAlchemyError:
            return {'status': 'unavailable'}, 503

    @app.get('/')
    def index():
        kind, query = request.args.get('kind',''), request.args.get('q','').strip()[:200]
        stmt = select(Organization).order_by(Organization.name)
        if kind in KINDS:
            stmt = stmt.where(Organization.kind == kind)
        if query:
            stmt = stmt.where(Organization.name.contains(query, autoescape=True))
        organizations = list(g.db.scalars(stmt))
        return render_template('index.html', organizations=organizations, latest=latest_map(), kind=kind, query=query,
            count_all=g.db.scalar(select(func.count()).select_from(Organization)), active='registry')

    @app.route('/organizations/new', methods=['GET','POST'])
    def new_org():
        if request.method == 'POST':
            name, kind = request.form.get('name','').strip(), request.form.get('kind','')
            try:
                if len(name) < 3 or len(name) > 600 or kind not in KINDS:
                    raise ValueError('Укажите название от 3 до 600 символов и тип учреждения.')
                url = normalize_url(request.form.get('url',''))
                if len(url)>512:
                    raise ValueError('Адрес слишком длинный.')
                validate_public(url)
                org = Organization(name=name, kind=kind, url=url)
                g.db.add(org)
                g.db.commit()
                flash('Учреждение добавлено.', 'success')
                return redirect(url_for('org_detail', oid=org.id))
            except (ValueError, FetchError) as exc:
                flash(str(exc), 'error')
            except IntegrityError:
                g.db.rollback()
                flash('Этот адрес уже есть в реестре.', 'error')
        return render_template('org_form.html', active='registry')

    @app.route('/organizations/<int:oid>', methods=['GET','POST'])
    def org_detail(oid):
        org = get_org(oid)
        if request.method == 'POST':
            try:
                hours = int(request.form.get('schedule_hours','0'))
                if hours not in (0,24,168):
                    raise ValueError('Выберите допустимое расписание.')
                urls = [normalize_url(line) for line in request.form.get('fact_sources','').splitlines() if line.strip()]
                if len(urls)>5:
                    raise ValueError('Можно указать максимум 5 внешних источников.')
                for url in urls:
                    validate_public(url)
                org.schedule_hours, org.fact_sources = hours, list(dict.fromkeys(urls))
                org.next_run = utcnow()+timedelta(hours=hours) if hours else None
                g.db.commit()
                flash('Настройки сохранены. Расписание работает, пока запущено приложение.', 'success')
                return redirect(url_for('org_detail', oid=oid))
            except (ValueError, FetchError) as exc:
                flash(str(exc), 'error')
        runs = list(g.db.scalars(select(Run).where(Run.org_id==oid).order_by(Run.id.desc()).limit(30)))
        return render_template('organization.html', org=org, runs=runs, active='registry')

    @app.post('/checks')
    def checks():
        try:
            ids = [int(i) for i in request.form.getlist('org_ids')]
        except ValueError:
            abort(400)
        if not ids:
            flash('Выберите хотя бы одно учреждение.', 'error')
            return redirect(url_for('index'))
        count = enqueue(g.db, ids[:500])
        flash(f'Добавлено проверок в очередь: {count}. Уже выполняющиеся проверки не дублируются.', 'success')
        return redirect(url_for('history'))

    @app.get('/history')
    def history():
        try:
            page = max(1, int(request.args.get('page','1')))
        except ValueError:
            page = 1
        runs = list(g.db.scalars(select(Run).order_by(Run.id.desc()).offset((page-1)*50).limit(51)))
        return render_template('history.html', runs=runs[:50], more=len(runs)>50, page=page, active='history',
                               polling=any(r.status in ('queued','running') for r in runs))

    @app.get('/runs/<int:rid>')
    def report(rid):
        run = get_run(rid)
        previous = g.db.scalar(select(Run).where(Run.org_id==run.org_id, Run.id<rid, Run.status=='completed').order_by(Run.id.desc()).limit(1))
        before = {r.rule:r for r in previous.results} if previous else {}
        current = {r.rule:r for r in run.results}
        fixed = [r for rule,r in before.items() if r.status in ('warning','error') and r.review!='dismissed'
                 and rule in current and current[rule].status=='pass']
        new = [r for r in run.results if r.status in ('warning','error') and r.review!='dismissed'
               and r.rule in before and before[r.rule].status=='pass']
        ordered = sorted(run.results, key=lambda r:(r.review=='dismissed',
            {'error':0,'warning':1,'unknown':2,'pass':3,'na':4}[r.status], {'high':0,'medium':1,'low':2}[r.priority]))
        return render_template('report.html', run=run, ordered=ordered, previous=previous, fixed=fixed, new=new,
                               active='reports', polling=run.status in ('queued','running'))

    @app.get('/runs/<int:rid>/progress')
    def progress(rid):
        run = get_run(rid)
        return {'status':run.status,'pages':run.pages_done}

    @app.post('/results/<int:result_id>/review')
    def review(result_id):
        result = g.db.get(Result,result_id)
        if not result:
            abort(404)
        value = request.form.get('review','')
        if value not in ('unreviewed','confirmed','dismissed'):
            abort(400)
        result.review = value
        result.review_note = request.form.get('note','').strip()[:2000]
        g.db.commit()
        flash('Решение специалиста сохранено.', 'success')
        return redirect(url_for('report', rid=result.run_id)+f'#result-{result.id}')

    def export_result(r):
        return {'rule':r.rule,'section':r.section,'status':r.status,'priority':r.priority,'title':r.title,
                'explanation':r.explanation,'recommendation':r.recommendation,'evidence':r.evidence,
                'review':r.review,'review_note':r.review_note}

    @app.get('/runs/<int:rid>/export.json')
    def export_json(rid):
        run = get_run(rid)
        value = {'id':run.id,'organization':run.organization.name,'url':run.meta.get('url_at_run',run.organization.url),
                 'status':run.status,'created_at_utc':run.created_at.isoformat(), 'meta':run.meta,
                 'results':[export_result(r) for r in run.results]}
        return Response(json.dumps(value,ensure_ascii=False,indent=2),mimetype='application/json',
            headers={'Content-Disposition':f'attachment; filename=audit-{rid}.json'})

    @app.get('/runs/<int:rid>/export.csv')
    def export_csv(rid):
        run = get_run(rid)
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(['Учреждение','Раздел','Статус','Приоритет','Проблема','Основание','Рекомендация','Источники','Решение специалиста'])
        def cell(value):
            s = str(value)
            return "'"+s if s.lstrip().startswith(('=','+','-','@')) else s
        for r in run.results:
            writer.writerow([cell(v) for v in [run.organization.name,r.section,STATUSES[r.status],PRIORITIES[r.priority],
                r.title,r.explanation,r.recommendation,'\n'.join(e.get('url','') for e in r.evidence),r.review]])
        return Response('\ufeff'+stream.getvalue(), content_type='text/csv; charset=utf-8',
            headers={'Content-Disposition':f'attachment; filename=audit-{rid}.csv'})

    @app.get('/comparison')
    def comparison():
        organizations = list(g.db.scalars(select(Organization).order_by(Organization.name)))
        # Completed results, rather than a later queued run, are used for comparison.
        sub = select(func.max(Run.id)).where(Run.status=='completed').group_by(Run.org_id)
        latest = {r.org_id:r for r in g.db.scalars(select(Run).where(Run.id.in_(sub)))}
        group = request.args.get('group','school')
        if group not in ('school','garden','spo'):
            group='school'
        members = [o for o in organizations if ('spo' if o.kind in ('college','technical') else o.kind)==group]
        def qualifies(o):
            run = latest.get(o.id)
            if not run:
                return False
            t=totals(run)
            return t['total']>=8 and t['coverage']>=70 and t['problems']==0 and not run.meta.get('limited')
        candidates = [o for o in members if qualifies(o)]
        reference = next((o for o in members if o.reference),None)
        differences = []
        if reference and reference.id in latest:
            def files(run):
                return {p.title.lower().strip():p for p in run.pages if p.category=='file' and p.status_code==200}
            reference_files = files(latest[reference.id])
            for org in members:
                if org.id not in latest or org.id==reference.id:
                    continue
                present=files(latest[org.id])
                missing=[p for name,p in reference_files.items() if name not in present]
                if missing:
                    differences.append((org,missing))
        return render_template('comparison.html',members=members,latest=latest,group=group,candidates=candidates,
            reference=reference,differences=differences,active='comparison')

    @app.post('/organizations/<int:oid>/reference')
    def reference(oid):
        org=get_org(oid)
        kinds=['college','technical'] if org.kind in ('college','technical') else [org.kind]
        for other in g.db.scalars(select(Organization).where(Organization.kind.in_(kinds))):
            other.reference=other.id==oid
        g.db.commit()
        flash('Эталон выбран специалистом. Это образец для сравнения, а не перечень юридических требований.', 'success')
        return redirect(url_for('comparison',group='spo' if org.kind in ('college','technical') else org.kind))

    @app.get('/methodology')
    def methodology():
        return render_template('methodology.html', active='methodology')

    @app.errorhandler(404)
    @app.errorhandler(400)
    @app.errorhandler(413)
    def user_error(error):
        return render_template('error.html', message=getattr(error,'description','Ошибка запроса'),active=''),error.code

    return app
