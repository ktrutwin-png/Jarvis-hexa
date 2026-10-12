# NexTrade Android / Heksa Core

NexTrade jest rozwijany **wyłącznie jako aplikacja na Androida**. Rdzeń Heksy odpowiada za analizę rynku, kontrolę bezpieczeństwa i lokalny dziennik operacji.

## Zakres zaimplementowanego kodu

- mobilny interfejs Flet przeznaczony na Androida,
- ekrany: Start, Sygnały, Portfel, Ustawienia i Rynki,
- skanowanie aktywnych par kryptowalutowych rozliczanych wyłącznie w EURC,
- ranking sygnałów z uwzględnieniem jakości rynku, kosztów, płynności, ryzyka i historii wyników,
- wycena salda Kraken w EURC z oznaczeniem aktywów bez dostępnej wyceny,
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

## Waluta handlu: EURC

Skaner wybiera wyłącznie aktywne pary krypto/EURC zwrócone przez API Kraken. Kwoty propozycji, limity, koszty i dziennik wyników są w EURC. Brak odpowiedniego rynku daje pusty wynik; aplikacja nie przełącza się automatycznie na EUR ani inną walutę. Również walidacja zleceń odrzuca pary z inną walutą kwotowaną lub walutą tradycyjną jako aktywem bazowym.

Portfel również pokazuje kwoty w EURC. Wycena korzysta z bezpośrednich kursów EURC, a dla pozostałych aktywów może wyliczać wartość przez bieżące kursy EUR i EURC/EUR. Jest to tylko odczyt danych do wyceny, nie trasa handlu. Nie zakładamy sztywnego kursu 1 EURC = 1 EUR. Stare wpisy w EUR pozostają w dotychczasowych tabelach SQLite; nowe tabele EURC nie mieszają ich z wynikami EURC. Ustawienie czasu odrzucania zostaje zachowane.

## Wybór rynków

Domyślnie bot bierze pod uwagę **wszystkie aktywne pary krypto/EURC**, wykrywane z API Kraken. Nowe pary nie wymagają zmiany kodu. Filtry płynności, spreadu, kosztów i strategii nadal obowiązują. Na ekranie Sygnały najwyżej oceniona propozycja jest wyróżniona; brak odpowiedniego sygnału nie wymusza transakcji.

Ekran **Rynki** pokazuje dostępność i pozwala wyłączyć tryb automatyczny oraz zapisać własny wybór. Lista obserwowana obejmuje XLM, XRP, ETH, SOL, BTC, ALGO, HBAR, ZBCN, FLR, XDC, ADA, LINK i AVAX oraz wszystkie inne aktywne rynki EURC wykryte w API. Nazwa na liście nie oznacza, że Kraken udostępnia bezpośrednią parę: niedostępne pozycje są wyraźnie oznaczone i nie trafiają do skanera. BTC jest mapowany na symbol XBT stosowany przez Kraken. Wybór jest zachowywany po restarcie.

## Odrzucanie propozycji w aplikacji

Na ekranie **Sygnały** przycisk **Odrzuć** zapisuje decyzję dla konkretnego identyfikatora propozycji i uruchamia nowy skan. Odrzucona para jest pomijana w obu kierunkach, domyślnie przez 30 minut. W **Ustawieniach** można wybrać 1–1440 minut; zmiana dotyczy kolejnych odrzuceń. Kilkukrotne dotknięcie nie tworzy kilku decyzji ani nie przedłuża czasu pomijania. Decyzja pozostaje zapisana także wtedy, gdy ponowny skan nie powiedzie się z powodu połączenia.

Nowa propozycja nadal musi spełniać kryteria strategii; odrzucenie nie gwarantuje lepszej okazji. Odrzucenia nie zamykają pozycji ani nie są liczone jako wyniki transakcji. Karty pokazują cenę odniesienia, szacunek kosztów wejścia i wyjścia oraz czas rozpoczęcia analizy. **Inwestuj** jest widoczne, ale nieaktywne, ponieważ wykonywanie rzeczywistych zleceń pozostaje wyłączone.

## Skaner na telefonie w stanie czuwania

Na ekranie Start lub Ustawienia wybierz **Włącz skanowanie w tle**. Android poprosi o powiadomienia oraz zgodę na pracę bez optymalizacji baterii. Skaner działa lokalnie; serwer ani jego abonament nie są potrzebne. Natychmiast wykonuje pierwszy skan, potem czeka 60 sekund po zakończeniu poprzedniego. Nie uruchamia nakładających się skanów, także przy ręcznym odświeżeniu. Błąd połączenia usuwa nieaktualną propozycję i jest ponawiany w kolejnym cyklu.

Natywna usługa pierwszoplanowa korzysta z `flutter_background` 1.3.1, częściowej blokady uśpienia procesora oraz Wi-Fi lock. Ekran może pozostać wyłączony. Stałe powiadomienie informuje o włączonym monitorowaniu. **Zatrzymaj skanowanie** wyłącza monitor i usługę, zwalnia blokady oraz usuwa alert propozycji. Monitor nie uruchamia się sam po restarcie aplikacji; wtedy trzeba go ponownie włączyć. Wymuszone zatrzymanie aplikacji, wyłączenie telefonu i ograniczenia producenta mogą przerwać pracę. Ciągłość w czuwaniu wymaga sprawdzenia na docelowym telefonie; sama kompilacja tego nie potwierdza.

Najwyżej oceniona, świeża propozycja trafia do lokalnego powiadomienia Androida. W tej rozwojowej wersji alert ma **Zobacz propozycję** i **Odrzuć**. Pierwszy otwiera szczegóły; drugi otwiera aplikację i zapisuje odrzucenie konkretnej aktualnej propozycji, po czym monitor od razu ponawia skan. Alert wygasa po maksymalnie 120 sekundach od rozpoczęcia analizy, również poprzez systemowy timeout powiadomienia. Otwarcie starego alertu pokazuje bieżący stan i nie może odrzucić nowej propozycji. Powtarzający się skan tych samych warunków nie przedłuża ważności ani nie zmienia identyfikatora. Żaden z przycisków powiadomienia nie wysyła zlecenia.

## Docelowy cykl scalpingu — jeszcze niewłączony

Po wdrożeniu pełnej obsługi zleceń **Inwestuj** ma zatwierdzać konkretny zakup kryptowaluty za EURC oraz pokazane zasady automatycznego wyjścia: realizację zysku, ograniczenie straty i limit czasu pozycji. Bot ma następnie sam sprzedać nabytą kryptowalutę za EURC, bez kolejnego potwierdzenia wyjścia. To powrót środków na saldo EURC w Krakenie, bez wypłaty poza giełdę. Kolejny zakup wymaga nowej zgody.

Warunkiem włączenia tej funkcji jest ponowna kontrola ceny, kosztów, salda i ryzyka przy zatwierdzeniu, obsługa częściowych wykonań i nieznanego statusu zlecenia, odtworzenie pozycji po restarcie oraz potwierdzona ochrona wyjścia po stronie giełdy na wypadek utraty telefonu lub sieci. Zysk jest ewentualny: saldo po zamknięciu może być niższe od zainwestowanej kwoty. Wynik musi uwzględniać rzeczywiste wykonania i wszystkie prowizje. Cykliczny skan 60 s nie jest jeszcze mechanizmem zarządzania otwartą pozycją.

## Budowanie APK

Każda zmiana dotycząca aplikacji Android, rdzenia, natywnego rozszerzenia lub konfiguracji uruchamia workflow `.github/workflows/android-apk.yml`. Po pomyślnym zakończeniu budowy plik jest publikowany jako artefakt `NexTrade-Android-APK.zip` w GitHub Actions.

Ręczne uruchomienie budowy:

1. Otwórz repozytorium w GitHubie.
2. Wejdź w **Actions**.
3. Wybierz **Build Android APK**.
4. Naciśnij **Run workflow**.
5. Po pomyślnym zakończeniu pobierz artefakt `NexTrade-Android-APK.zip`.
6. Rozpakuj archiwum. Plikiem instalacyjnym jest `nextrade-android.apk`; plik `SHA256SUMS` służy do kontroli zgodności pobrania.

Kompilacja APK nie potwierdza jeszcze uruchomienia na konkretnym telefonie. Obecne pakiety są rozwojowe i nie uruchamiają handlu prawdziwymi środkami.

Lokalne polecenie dla przygotowanego środowiska Flet:

```bash
uv run python scripts/build_android.py build apk --python-version 3.12 --verbose
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
6. poranny raport,
7. weryfikacja działania w czuwaniu na docelowym telefonie,
8. podpisywanie wersji instalacyjnych i bezpieczne aktualizacje.

Projekt nie jest już rozwijany dla Windowsa. Cały interfejs, pakowanie, bezpieczeństwo urządzenia i optymalizacja wydajności są podporządkowane Androidowi.

