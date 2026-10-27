# Samtalelogg – Viktor Game API

Denne filen dokumenterer samtalen om spillbackend, statistikk og innlogging.
Nye meldinger og avklaringer kan legges til nederst, i kronologisk rekkefølge.
Tidspunktene gjelder brukermeldingene og er oppgitt i norsk lokal tid (UTC+01:00).
Verktøyutdata er utelatt. Svarene beskriver situasjonen da de ble gitt;
se `README.md` for gjeldende oppsett og bruksanvisning.

## 1. Valg av API og skybackend

**Dato:** 2026-10-27 kl. 18:45:49

### Bruker

Hva vil være et bra api for en server i en sky-tjeneste som samler opp high scores og annet relevant som backend for et spill. Vi vil gjerne at man skal kunne samle statistikk og sammenligne seg med andre spillere.

### Assistent

Et godt utgangspunkt er et **REST-API med PostgreSQL som database**, der spillklienten sender inn resultater, og serveren håndterer topplister, statistikk og sammenligning mellom spillere. Dere trenger sannsynligvis ikke GraphQL eller en komplisert arkitektur for dette.

**Jeg ville vurdert disse alternativene:**

| Løsning | Passer best når |
|---|---|
| **Supabase** | Dere vil komme raskt i gang med PostgreSQL, innlogging og API, men beholde fleksibiliteten til å bygge egne spillfunksjoner. |
| **PlayFab** | Dere ønsker en ferdig spillbackend med spillerkontoer, statistikk og topplister. Mindre egen backendkode, men større binding til plattformen. |
| **Eget API med FastAPI eller ASP.NET Core + PostgreSQL** | Dere vil ha full kontroll over spillregler, datamodell og integrasjoner, og kan ta ansvar for drift og sikkerhet. |

**For et mindre team ville jeg normalt startet med Supabase**, med serverfunksjoner for innsending og validering av resultater. PlayFab er et godt alternativ hvis dere vil bruke mest mulig ferdig spillfunksjonalitet.

Et API dere bygger selv, kan for eksempel ha disse endepunktene:

```http
POST /v1/runs                        # Send inn resultat fra en spillrunde
GET  /v1/leaderboards/{id}           # Toppliste for spillmodus/sesong
GET  /v1/leaderboards/{id}/me        # Egen plassering og spillere rundt deg
GET  /v1/players/{id}/stats          # Statistikk som kan deles med andre
GET  /v1/me/stats                   # Egen detaljert statistikk
```

Lagre **spillrunder, ikke bare beste poengsum**. Da kan dere beregne personlig rekord, utvikling over tid, antall forsøk, seiersprosent og sesongstatistikk. Topplistene bør skille mellom spillmodus, vanskelighetsgrad og eventuelt spillversjon, slik at sammenligningene blir rettferdige.

Det viktigste er likevel **å ikke stole blindt på poengsummen klienten sender inn**. Serveren bør validere resultatene, hindre at samme runde registreres flere ganger, og begrense innsendinger. I konkurransepregede spill kan det være nødvendig med serverberegnede resultater eller verifiserbare rundedata. Bruk spiller-ID fra innloggingen, og skill mellom privat statistikk og det andre spillere får se.

## 2. Treff, bomskudd, drepte fiender og spilletid

**Dato:** 2026-10-27 kl. 18:52:37

### Bruker

Kan vi legge til antall treff, antall bomskudd, og antall drepte fiender og total spiltid

### Assistent

Ja! Vi kan registrere dette **per spillrunde**, og summere det til totalstatistikk for hver spiller.

Et resultat sendt til `POST /v1/runs` kan se slik ut:

```json
{
  "runId": "c1b65cbb-42cb-4b9e-88ba-cbcf53bd7860",
  "score": 12500,
  "hits": 85,
  "misses": 15,
  "enemiesKilled": 32,
  "playTimeSeconds": 420
}
```

Da kan vi vise følgende på spillerprofilen:

| Statistikk | Beregning |
|---|---|
| Antall treff | Sum treff fra alle runder |
| Antall bomskudd | Sum bomskudd fra alle runder |
| Drepte fiender | Sum drepte fiender fra alle runder |
| Total spiltid | Sum aktiv spilletid, vist som timer og minutter |
| Treffsikkerhet | Treff / (treff + bomskudd) × 100 % |

**Spilletid bør telle aktiv spilling**, ikke tid i pausemenyer. Serveren bør avvise negative verdier og sørge for at samme `runId` ikke telles flere ganger.

Vi bør også definere hva et treff betyr: Hvis ett skudd kan treffe flere fiender, bør `hits` telle **skudd som traff**, ikke antall fiender truffet. Da blir treffsikkerheten riktig og aldri over 100 %.

## 3. Innlogging fra Python-spillet

**Dato:** 2026-10-27 kl. 18:54:33

### Bruker

Vi må også ha en login, spillet er laget i python, hva vil være den enkleste men tryggeste måten å få til dette på?

### Assistent

**Jeg ville valgt Supabase Auth til innlogging, og latt Python-spillet bruke Supabase sitt Python-bibliotek.** Det er en enkel og trygg løsning fordi dere slipper å bygge passordlagring, passordtilbakestilling og håndtering av innlogging selv.

For en første versjon er **e-post og passord med e-postbekreftelse** et greit valg. Supabase håndterer passordene; spillserveren deres skal aldri lagre dem selv.

Flyten blir slik:

1. Spilleren oppretter konto eller logger inn fra spillet.
2. Supabase returnerer et kortlivet tilgangstoken og et fornyelsestoken.
3. Spillet sender tilgangstokenet når det leverer resultater til API-et deres.
4. API-et verifiserer tokenet og knytter resultatet til riktig spiller.

Eksempel fra Python-klienten:

```python
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)

response = supabase.auth.sign_in_with_password({
    "email": email,
    "password": password,
})

session = response.session
if session is None:
    raise RuntimeError("Innloggingen opprettet ingen sesjon")
```

Ved innsending av en spillrunde:

```python
import requests

response = requests.post(
    f"{API_URL}/v1/runs",
    headers={
        "Authorization": f"Bearer {session.access_token}",
    },
    json={
        "runId": run_id,
        "score": 12500,
        "hits": 85,
        "misses": 15,
        "enemiesKilled": 32,
        "playTimeSeconds": 420,
    },
    timeout=15,
)
response.raise_for_status()
```

**De viktigste sikkerhetsreglene er:**

- Bruk HTTPS. API-et må verifisere tokenets signatur, utløpstid, utsteder og målgruppe — ikke bare lese innholdet.
- Finn spiller-ID fra det verifiserte tokenet, aldri fra en spiller-ID klienten selv sender.
- Bare Supabase sin **publiserbare nøkkel** skal være i spillet. Hemmelige nøkler og `service_role` må kun ligge på serveren.
- Hvis dere tilbyr «husk meg», lagre fornyelsestokenet i operativsystemets sikre nøkkellager, for eksempel via Python-pakken `keyring`. Ikke lagre passord eller tokens i en vanlig fil.
- Bruk tilgangsregler i databasen, slik at spillere ikke kan endre andres data eller skrive direkte til topplistene.

Min anbefaling er dermed **Python-spill → FastAPI → Supabase/PostgreSQL**, med **Supabase Auth for innlogging**. Innlogging identifiserer spilleren, men hindrer ikke juks alene; resultater må fortsatt valideres på serveren.

## 4. Implementering og valg av Java

**Dato:** 2026-10-27 kl. 18:56:24

### Bruker

Dette høres bra ut, implementer

### Assistent – avklaring

Prosjektet inneholder foreløpig bare en Java-startfil. Skal jeg opprette Python-backenden med FastAPI og Supabase her, slik vi diskuterte?

Alternativene som ble presentert:

1. Ja, opprett Python-backenden her (anbefalt)
2. Bruk Java til backenden i dette prosjektet

### Bruker – valgt alternativ

Bruk Java til backenden i dette prosjektet

### Assistent – statusmelding

Jeg setter opp Java-backenden med Spring Boot, Supabase-innlogging og PostgreSQL. Jeg legger også til lagring av spillrunder, spillerstatistikk og topplister, samt et Python-eksempel som viser hvordan spillet logger inn og sender resultater. Passord håndteres av Supabase, ikke av Java-serveren.

### Assistent – statusmelding

Java-API-et er på plass med tokenverifisering og beskyttelse mot dobbel registrering av spillrunder. Detaljert statistikk er privat som standard; spilleren kan velge å dele den, mens poengsummene vises i topplistene. Nå legger jeg til Python-klienten og oppsettbeskrivelsen for Supabase.

### Assistent – avsluttende svar

Implementert i **Java med Spring Boot**, med et Python-klienteksempel for spillet.

- **Innlogging via Supabase**, med verifisering av tilgangstokens.
- **Lagring i PostgreSQL** av poeng, treff, bomskudd, drepte fiender og aktiv spilletid.
- **Spillerstatistikk og topplister**, inkludert treffsikkerhet og egen plassering.
- Beskyttelse mot dobbeltregistrering av spillrunder og valgfri deling av detaljert statistikk.
- Docker-oppsett for utrulling.

Oppsettet er beskrevet i [README.md](README.md). Python-integrasjonen ligger i [examples/python/game_client.py](examples/python/game_client.py).

**Supabase må konfigureres før løsningen kan tas i bruk.** Legg inn miljøvariablene fra `.env.example`, og start med `mvn spring-boot:run`. Løsningen er ikke publisert til skyen eller koblet til deres spill ennå. Resultatene er klientrapporterte; konkurranser som krever beskyttelse mot juks trenger også spillspesifikk resultatvalidering.

## 5. Dokumentasjon av samtalen

**Dato:** 2026-10-27 kl. 19:08:49

### Bruker

Skriv ned logg med det jeg har spurt om og det du har svart på i en md-fil. Denne kan oppdateres underveis for å dokumentere vår konversasjon.

### Assistent

Opprettet [SAMTALELOGG.md](SAMTALELOGG.md) med spørsmålene dine, svarene mine og avklaringen om å bruke Java. Jeg oppdaterer loggen videre underveis i samtalen.
