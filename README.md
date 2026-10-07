# Heksa Core
Lokalny rdzeń Heksy — wersja 0.2.0.

## Co działa
- Koordynator HeksaCore i lokalny System Agent.
- Security Agent sprawdza każdą akcję przekazywaną agentom według jawnej listy uprawnień.
- Dziennik decyzji w katalogu użytkownika: `.heksa/audit.jsonl`.
- Konsola: `status`, `time`, `hello`, `agents`, `help`, `exit`.
- Trwała kolejka SQLite: `queue status`, `queue time`, `tasks`, `run-next`, `cancel <id>`.
- Uprawnienia są sprawdzane przy dodaniu zadania i ponownie przed wykonaniem.
- Zadania zakończone i anulowane nie są wykonywane ponownie.

## Pamięć zadań
Zadania są zapisywane w `.heksa/tasks.sqlite3` w katalogu użytkownika.
`run-next` wykonuje jedno oczekujące zadanie. Kolejka obsługuje obecnie tylko
lokalne akcje `status` i `time`, bez usług zewnętrznych.
Nie ma jeszcze automatycznego pracownika w tle.
Po awarii zadanie w stanie `running` nie jest automatycznie powtarzane:
wynik działania może być nieznany. Programistyczne `interrupt_running()`
oznacza takie zadania jako `interrupted`; używaj go dopiero po potwierdzeniu,
że poprzedni pracownik zakończył działanie. Brak automatycznych ponowień
chroni przed powieleniem przyszłych działań zewnętrznych.

Security Agent jest kontrolą na poziomie aplikacji, nie piaskownicą systemu operacyjnego.
Nie chroni przed złośliwym kodem z dostępem do tego samego procesu lub plików.
Dziennik jest lokalny i nie ma zabezpieczenia przed modyfikacją.

## Windows
Wymagany Python 3.10 lub nowszy. Brak dodatkowych zależności.
Pobierz repozytorium (Code → Download ZIP), rozpakuj i otwórz `start_windows.bat`.
Alternatywnie w folderze projektu uruchom `py -3 -m heksa`.

## Android / Termux
W folderze projektu uruchom `python -m heksa`. To konsola, jeszcze nie aplikacja Android.

## Testy
`python -m unittest discover -s tests -v`

## Stan projektu
To działający fundament lokalny. Nie zawiera jeszcze interfejsu z kulą,
rozpoznawania głosu, integracji Gemini, poczty, kalendarza, komunikatorów,
handlu kryptowalutami ani automatycznych aktualizacji i rollbacków agentów.
Nie działa samoczynnie w tle i nie jest zainstalowany na laptopie użytkownika.

Kolejne etapy: interfejs, trwały rejestr agentów i wersji, zatwierdzanie
aktualizacji z rollbackiem, a następnie integracje testowane osobno.
Nie umieszczaj haseł ani kluczy API w repozytorium.
