# Kommunale Mødeudtræk

Dette projekt er en Streamlit-applikation, der giver mulighed for at søge og analysere mødereferater fra danske kommuner. Applikationen bruger PostgreSQL til at gemme data og udføre avanceret dansk tekstsøgning.

## Funktioner

Applikationen har to hovedfunktioner, der er tilgængelige via separate faner:

### Søg i Kommunale Møder
I denne sektion kan brugere søge gennem mødereferater ved hjælp af:
- Fritekst-søgning med dansk sprogsupport
- Filtrering efter kommune
- Datoafgrænsning
- Visning af mødedetaljer inklusive beslutninger og fremtidige handlinger
- Automatisk søgning efter relaterede nyhedsartikler

### Populære Emner
Denne sektion giver et overblik over de mest diskuterede emner i kommunerne gennem:
- Samlet visning af populære kategorier på tværs af alle kommuner
- Fordeling af kategorier per kommune
- Detaljeret visning af enkelte kommuners emnefordeling

## Teknisk Setup

### Forudsætninger
- Python 3.9 eller nyere
- PostgreSQL 16 eller nyere
- Adgang til en PostgreSQL database

### Installation

1. Klon projektet:
```bash
git clone [repository-url]
cd kommunale-modeudtraek
```

2. Installer de nødvendige Python-pakker:
```bash
pip install -r requirements.txt
```

3. Opret en `.env` fil med følgende variabler:
```
DB_NAME=dit_database_navn
DB_USER=din_database_bruger
DB_PASSWORD=dit_database_password
DB_HOST=din_database_host
DB_PORT=5432
```

### Database Setup

Applikationen kræver en PostgreSQL database med:
- Et materialized view til tekstsøgning
- Dansk sprog-support for fuld-tekst søgning
- To hovedtabeller: source.referater og source.subjects

## Kørsel af Applikationen

Start applikationen lokalt:
```bash
streamlit run app.py
```

## Deployment

Applikationen er designet til at kunne deployes på Render.com. For at deploye:

1. Push koden til et GitHub repository
2. Opret en ny Web Service på Render
3. Forbind til GitHub repositoriet
4. Konfigurer environment variables i Render
5. Deploy

## Vedligeholdelse

Materialized view'et opdateres automatisk når:
- Der tilføjes nye mødereferater
- Der foretages ændringer i eksisterende referater
- Der udføres en manuel opdatering via refresh_materialized_view() funktionen

## Bidrag

Projektet er åbent for bidrag. Ved bidrag, venligst:
1. Fork repositoriet
2. Opret en feature branch
3. Commit dine ændringer
4. Push til branchen
5. Opret et Pull Request

## Support

Ved spørgsmål eller problemer, opret venligst et issue i GitHub repositoriet.

