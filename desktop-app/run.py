import argparse
from pathlib import Path


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Gosweb Audit — проверка сайтов образовательных организаций")
    parser.add_argument("--run-all", action="store_true", help="проверить весь реестр без открытия окна")
    parser.add_argument("--kind", choices=("school", "garden", "all"), default="all",
                        help="тип учреждений для пакетной проверки")
    args = parser.parse_args()

    if args.run_all:
        from edu_audit.service import AuditService
        from edu_audit import storage

        service = AuditService()
        service.initialize()
        organizations = storage.list_organizations(service.db_path,
                                                   None if args.kind == "all" else args.kind)
        if not organizations:
            print("В реестре нет учреждений для проверки.")
            raise SystemExit(0)
        failures = 0
        for index, organization in enumerate(organizations, start=1):
            print(f"[{index}/{len(organizations)}] {organization['name']} — {organization['url']}", flush=True)
            try:
                report = service.audit(organization, progress=lambda message: print("  " + message, flush=True))
                print(f"  Завершено: страниц {len(report['pages'])}, сигналов {len(report['findings'])}.", flush=True)
            except Exception as exc:
                failures += 1
                print(f"  Ошибка проверки: {exc}", flush=True)
        print(f"Пакетная проверка завершена: организаций {len(organizations)}, ошибок {failures}.")
        raise SystemExit(1 if failures else 0)

    from edu_audit.gui import run_gui
    run_gui()
