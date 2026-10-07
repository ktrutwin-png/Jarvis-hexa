from .core import HeksaCore

def main():
    try:
        core = HeksaCore()
        print("HEKSA CORE ONLINE — lokalny prototyp")
        print(core.process("help"))
        while True:
            command = input("TY > ")
            if command.strip().lower() in {"exit", "quit"}:
                break
            print("HEKSA >", core.process(command))
    except (EOFError, KeyboardInterrupt):
        print("\nHeksa zakończyła pracę.")
    except (OSError, PermissionError) as error:
        print("Błąd uruchomienia lub dziennika:", error)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
