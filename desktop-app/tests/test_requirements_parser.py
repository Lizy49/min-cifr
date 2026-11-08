from edu_audit.requirements_parser import parse_text


def test_parser_extracts_explicit_numeric_requirements():
    result = parse_text(
        "Новости должны публиковаться не реже одного раза в 14 дней.\n"
        "Новость о прошедшем мероприятии должна быть опубликована в течение 24 часов.\n"
        "Проверить мероприятия текущего и следующего квартала."
    )
    assert result["total"] == 3
    assert result["requirements"][0]["threshold"] == {"max_interval_days": 14}
    assert result["requirements"][1]["threshold"] == {"max_delay_hours": 24}
    assert result["requirements"][2]["threshold"] == {"quarters_ahead": 2}
    assert all(item["review_required"] for item in result["requirements"])


def test_parser_keeps_ambiguous_requirements_for_manual_review():
    result = parse_text("Необходимо проверить качество фотографий и актуальность контактной информации.")
    assert result["total"] == 1
    assert result["requirements"][0]["verification"] == "presence_or_content"
    assert result["requirements"][0]["threshold"] == {}


def test_parser_deduplicates_repeated_lines():
    result = parse_text("Проверить раздел документов на сайте учреждения.\nПроверить раздел документов на сайте учреждения.")
    assert result["total"] == 1
