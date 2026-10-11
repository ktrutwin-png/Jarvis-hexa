# Kraken Trade Android

Niezależna od Heksy aplikacja Android do prezentowania propozycji transakcji Kraken.

## Zasada bezpieczeństwa
- analiza może działać automatycznie,
- aplikacja prezentuje wejście, stop-loss, take-profit i limit ryzyka,
- wejście na rynek wymaga ręcznego zatwierdzenia użytkownika,
- przycisk zatwierdzenia pozostaje wyłączony, dopóki nie istnieje kompletna propozycja,
- klucze API nie są przechowywane w repozytorium,
- warstwa wykonawcza i automatyczne wyjście zostaną podłączone po testach jednostkowych i integracyjnych.


## Koszt
- aplikacja korzysta wyłącznie z darmowych bibliotek i narzędzi,
- brak płatnych modeli AI i płatnych pośrednich API,
- komunikacja z rynkiem odbywa się bezpośrednio przez API Kraken,
- build i testy są przygotowane tak, aby nie wymagały płatnej infrastruktury,
- ewentualne opłaty transakcyjne giełdy Kraken nie są kosztem aplikacji i zależą od konta użytkownika oraz wykonanych transakcji.
