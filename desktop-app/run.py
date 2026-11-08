from edu_audit.gui import run_gui


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass
    run_gui()
