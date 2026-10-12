# NexTrade Android / Heksa Core

NexTrade jest rozwijany **wyłącznie jako aplikacja na Androida**. Rdzeń Heksy odpowiada za analizę rynku, kontrolę bezpieczeństwa i lokalny dziennik operacji.

## Zakres zaimplementowanego kodu

- mobilny interfejs Flet przeznaczony na Androida,
- ekrany: Start, Sygnały, Portfel i Ustawienia,
- skanowanie aktywnych par kryptowalutowych rozliczanych w EUR,
- ranking sygnałów z uwzględnieniem jakości rynku, kosztów, płynności, ryzyka i historii wyników,
- wycena salda Kraken w EUR z oznaczeniem aktywów bez dostępnej wyceny,
- blokada nakładających się skanowań rynku,
- przycisk „Odrzuć” przy propozycji: trwały zapis decyzji i natychmiastowy ponowny skan,
- konfigurowalny czas pomijania odrzuconej pary, odporny na restart aplikacji,
- szyfrowane przechowywanie kluczy Kraken przez Android Keystore,
- lokalny dziennik sygnałów, decyzji i wyników w trwałym katalogu danych aplikacji,
- Security Agent kontrolujący dozwolone działania,
- automatyczne budowanie instalacyjnego APK w GitHub Actions.

## Aktualny tryb bezpieczeństwa

Aplikacja analizuje rynek, pokazuje propozycje i odczytuje portfel. **Prawdziwe składanie zleceń jest obecnie wyłączone.** Zostanie uruchomione dopiero po dodaniu pełnego cyklu zlecenia, twardych limitów ryzyka, ochrony przed duplikacją i ręcznego zatwierdzania.

Dla NexTrade należy utworzyć osobny klucz Kraken z minimalnymi uprawnieniami. Nigdy nie wolno włączać prawa do wypłat. Kluczy, haseł i innych sekretów nie umieszczamy w repozytorium ani dziennikach.

## Odrzucanie propozycji w aplikacji

Na ekranie **Sygnały** przycisk **Odrzuć** zapisuje decyzję dla konkretnego identyfikatora propozycji i uruchamia nowy skan. Odrzucona para jest pomijana w obu kierunkach, domyślnie przez 30 minut. W **Ustawieniach** można wybrać 1–1440 minut; zmiana dotyczy kolejnych odrzuceń. Kilkukrotne dotknięcie nie tworzy kilku decyzji ani nie przedłuża czasu pomijania. Decyzja pozostaje zapisana także wtedy, gdy ponowny skan nie powiedzie się z powodu połączenia.

Nowa propozycja nadal musi spełniać kryteria strategii; odrzucenie nie gwarantuje lepszej okazji. Odrzucenia nie zamykają pozycji ani nie są liczone jako wyniki transakcji. Karty pokazują cenę odniesienia, szacunek kosztów wejścia i wyjścia oraz czas rozpoczęcia analizy. **Inwestuj** jest widoczne, ale nieaktywne, ponieważ wykonywanie rzeczywistych zleceń pozostaje wyłączone. Obsługa dotyczy obecnie ekranu aplikacji; powiadomienia systemowe Android są osobnym etapem.

## Budowanie APK

Każda zmiana dotycząca aplikacji Android, rdzenia lub konfiguracji uruchamia workflow `.github/workflows/android-apk.yml`. Po pomyślnym zakończeniu budowy plik jest publikowany jako artefakt `flet-apk.zip` w GitHub Actions.

Ręczne uruchomienie budowy:

1. Otwórz repozytorium w GitHubie.
2. Wejdź w **Actions**.
3. Wybierz **Build Android APK**.
4. Naciśnij **Run workflow**.
5. Po pomyślnym zakończeniu pobierz artefakt `flet-apk.zip`.
6. Rozpakuj archiwum. Plikiem instalacyjnym jest `nextrade-android.apk`; plik `.sha1` służy do kontroli zgodności pobrania.

Kompilacja APK nie potwierdza jeszcze uruchomienia na konkretnym telefonie. Obecne pakiety są rozwojowe i nie uruchamiają handlu prawdziwymi środkami.

Lokalne polecenie dla przygotowanego środowiska Flet:

```bash
flet build apk --verbose
```

## Struktura

- `android_app/` — interfejs i punkt startowy aplikacji na Androida,
- `heksa/` — rdzeń, bezpieczeństwo, Kraken, skaner rynku, portfel i dziennik,
- `tests/` — testy jednostkowe rdzenia,
- `.github/workflows/android-apk.yml` — automatyczne budowanie APK,
- `pyproject.toml` — konfiguracja aplikacji i pakowania Androida.

## Najbliższe etapy

1. pełny, bezpieczny cykl zlecenia Kraken,
2. tryb symulacji i ręczne zatwierdzanie transakcji,
3. twarde limity straty i awaryjne zatrzymanie,
4. dane strumieniowe oraz wykrywanie utraty połączenia,
5. rzeczywisty P&L uwzględniający prowizję i cenę wykonania,
6. powiadomienia Android i poranny raport,
7. niezawodne działanie w tle,
8. podpisywanie wersji instalacyjnych i bezpieczne aktualizacje.

Projekt nie jest już rozwijany dla Windowsa. Cały interfejs, pakowanie, bezpieczeństwo urządzenia i optymalizacja wydajności są podporządkowane Androidowi.

