# Analisi del codice e dello storico

**Stato aggiornato:** 24 novembre 2026. L'analisi distingue il server di teleoperazione dal controllore sperimentale `modules/follow_route.py`; il completamento di una corsa sul Rover fisico non è confermato.

## Perimetro esaminato

Nel repository sono presenti `telemetry_server.py`, i moduli GPS/IMU/motori, client Rover RTCM/TCP, geometria Pure Pursuit, controllore da terminale, script e pagine HTML. L'`index` offre una UI per disegnare e modificare perimetri GeoJSON salvati nel `localStorage` del browser; questa selezione non viene trasferita automaticamente al controllore. La pagina Riproduzione può salvare un GeoJSON sul Rover; il controllore sperimentale legge il file locale fissato nel codice. È presente il trasporto RTCM su TCP privato e la scrittura seriale al ricevitore; non è un servizio NTRIP. `modules/follow_route.py` collega Pure Pursuit al driver motori per una tratta in avanti supervisionata. I file in `tests/` comprendono sia programmi hardware dimostrativi sia test unitari.

## Funzionalità effettivamente presenti

| Componente | Comportamento osservato | Limite rilevante |
|---|---|---|
| `telemetry_server.py` | Server aiohttp su porta 8080; WebSocket `/ws`; telemetria GPS/IMU a 5 Hz; comandi motori; watchdog software da 1 s; client RTCM/TCP opzionale; registrazione JSON versione 3 a ogni nuovo GGA (normalmente 1 Hz), con campi motore e diagnostica. Applica e salva il trim differenziale prima del driver. | Nessuna autenticazione/autorizzazione; servizi esposti sulle interfacce configurate; il server offre solo anteprima della traccia, senza avvio della corsa. La registrazione ammette qualità diverse da FIX. |
| `modules/gps.py` | Parsing di GGA/RMC NMEA, qualità GGA, satelliti, altitudine, velocità e heading; scrittura RTCM tramite lo stesso proprietario seriale. | Non verifica checksum; il parser non costituisce una garanzia di integrità assoluta; l'uscita FIX va validata per freschezza e uso in movimento. |
| `modules/imu.py` | Lettura del frame angolare `0x55 0x53` da UART e decodifica roll/pitch/yaw; yaw usato dal controllore sperimentale dopo allineamento iniziale. | Nessuna verifica checksum/frame completo, calibrazione assoluta o diagnostica di deriva; heading non equivale automaticamente a direzione di marcia affidabile. |
| `modules/motor.py` | Segnali servo a 50 Hz, 1000–2000 µs mappati linearmente a -100…100%; controllo differenziale. | Nessun feedback encoder/velocità, diagnostica di guasto o arresto hardware. La rampa è nel controllore sperimentale, non nel driver. Il valore neutro PWM non prova che il veicolo si arresti in ogni guasto. |
| `modules/route_replay.py`, `modules/follow_route.py` | Validano missione, FIX, freschezza RTCM/IMU e geofence locale; il controllore da terminale converte velocità e curvatura in comandi motore con limite e rampa, e richiede presenza continua dell'operatore. | Sono funzioni sperimentali separate dal server web; nessun monitor ostacoli integrato, feedback ruote o prova completa in campo. Il geofence fisso deve ancora essere verificato rispetto all'ingombro e all'arresto. |
| `static/autopilota.html` | Interfaccia video, telemetria, comandi manuali, selettore dry-run, registrazione e slider trim differenziale. I comandi nominali visualizzati restano distinti dalle percentuali effettive al driver. | “Autopilota” è il nome della pagina: invia ancora comandi manuali incrementali. Non c'è esecuzione automatica della traccia o controllo Pure Pursuit. |
| `static/index.html` | Mappa live Rover/Base e strumenti di disegno, modifica e rimozione dei perimetri; i poligoni sono salvati localmente nel browser. | La selezione della mappa non configura il file geofence usato da `follow_route.py`; Leaflet-Geoman è uno strumento di configurazione UI, non una funzione di sicurezza. |
| `static/scatter_analysis.html` | Accumula i fix GNSS Rover via WebSocket durante l'analisi; evita duplicati tramite timestamp del fix. | Il Rover pubblica la posizione di riferimento ricavata da `GET /api/state` o configurata manualmente. Scatter Analysis richiede un timestamp di fix Base e scarta quindi la posizione di riferimento. I dati non sono persistiti tra sessioni. |
| `tests/test_lidar.py`, `tests/test_camera.py` | Prototipi autonomi per visualizzare dati LiDAR e streaming camere. | Non sono integrati come supervisione di sicurezza del rover; un sensore mostrato in una pagina non costituisce una protezione validata. |

### Flusso di comando attuale

La pagina web si collega al WebSocket e invia `motor_step`; il server traduce i tasti in gradini da 10% (primo gradino 20%). Un heartbeat della pagina ogni 800 ms rinnova il watchdog. Quando il watchdog scade, `stop_all_motors()` porta i comandi a zero. Questa è una protezione contro alcune perdite di connessione, non un arresto di emergenza certificabile: dipende dallo stesso processo Linux, dalla stessa rete e dalla stessa elettronica che comandano il veicolo.

Il trim applica una correzione relativa a SX/DX al confine del driver e la salva nel file JSON di calibrazione (predefinito `/home/terminator/Documents/motor_calibration.json`). I punti registrano comando nominale, trim, uscita effettiva, PWM, stato GNSS/RTCM, IMU e relative età. Gli eventi motore sono salvati in `diagnostic_events`; sono dati passivi e non entrano nel calcolo dei comandi.

Il messaggio `estop` è solo un comando WebSocket; non è collegato a un circuito di emergenza fisico indipendente. Inoltre il server non comanda un apparato di taglio: lo stop software oggi può fermare le ruote comandate, non una lama che non è rappresentata nel progetto.

## Discrepanze con `Storico Google.md`

`Storico Google.md` non è presente in questo checkout. Le note storiche usate per questa analisi raccoglievano snapshot, script e requisiti desiderati, non una specifica coerente dell'implementazione corrente. In particolare:

- lo storico parla di ritorno a casa, PID, encoder, batteria/BMS, rilevamento ostacoli e NTRIP: queste funzioni non sono implementate. Sono invece presenti validazione del geofence locale e inseguimento di una tratta in avanti con supervisione da terminale, senza prova completa sul Rover fisico;
- lo storico propone LC29H a 460800 baud, mentre `modules/gps.py` e il server impostano 115200;
- lo storico nomina una MPU-6050 su I²C, mentre il codice presente legge una WT61/seriale `/dev/ttyAMA4`;
- gli script `test_record_gps.py` e `test_lidar.py` sono progetti/prototipi autonomi e non sono chiamati dal server;
- il registratore attuale aggiunge un campione per nuovo aggiornamento GGA (circa 1 Hz) e scarta coordinate nulle o dati più vecchi di 3 s; conserva in ciascun punto la qualità RTK e può registrare `FIX`, `FLOAT`, `DGPS` o `SINGLE`. La traccia non va considerata tutta FIX senza filtrare il campo `rtk_status`;
- `Fix_1.json`, acquisita prima dell'aggiunta dei campi motore, è utile come traccia GPS ma non permette la calibrazione velocità/comando;
- lo storico contiene comandi distruttivi di terminazione forzata dei processi e istruzioni di avvio per host diversi. Sono stati letti come testo di riferimento e non eseguiti.

Prima di usare lo storico come fonte tecnica, occorre verificare sul rover reale modello, cablaggi, baud rate, porte seriali, driver e firmware GNSS.

## Vulnerabilità e guasti prioritari

Classificazione qualitativa: **Critica** significa che può consentire il movimento non autorizzato o non controllato; **Alta** può rendere la navigazione o il controllo non affidabili; **Media** può compromettere dati o disponibilità.

| Priorità | Rilievo | Conseguenza plausibile | Mitigazione richiesta |
|---|---|---|---|
| Critica | WebSocket senza autenticazione, su `0.0.0.0:8080`, in chiaro se servito via HTTP; stream `ustreamer` su `0.0.0.0:8081`. | Un host raggiungibile può inviare comandi motore, cambiare dry-run, avviare/fermare registrazioni o vedere il video. | Isolare la rete; autenticazione e autorizzazione robuste; TLS; allowlist/origin e protezione CSRF dove applicabile; video protetto; firewall e credenziali gestite fuori dal codice. Non esporre direttamente a Internet. |
| Critica | Nessuna separazione fra teleoperazione e comando di sicurezza; heartbeat condiviso tra tutti i client e rinnovato anche senza comando di guida. | Un client inatteso può tenere vivo il watchdog; più client possono contendersi comando e dry-run. Il watchdog non è un dead-man switch tenuto dall'operatore. | Un solo controllore autorizzato con lease; comando di marcia valido solo con dead-man esplicito; timeout indipendente e hardware che disabilita coppia/attrezzo; pulsanti fisici a bordo e stop remoto verificato. |
| Alta | I comandi manuali non sono bloccati se GNSS è degradato o obsoleto; il logger filtra i dati più vecchi di 3 s ma registra anche `FLOAT`, `DGPS` e `SINGLE`, oltre a `FIX`. | Operatore o funzione futura possono usare posizione non adeguata alla precisione RTK richiesta; la traccia può contenere qualità diverse. | Mostrare qualità/età chiaramente; imporre requisiti RTK nel futuro controllore autonomo; per analisi di precisione selezionare esplicitamente `FIX`; valutare outlier. |
| Alta | La registrazione conserva qualità e freschezza, ma non applica ancora filtro di salti/spike né verifica la ripetibilità su punti noti. | Una traccia può contenere salti di posizione o errori sistematici che si ripeterebbero nel playback. | Aggiungere controllo outlier, validazione geometrica e prove di accuratezza/ripetibilità; non eseguire automaticamente una traccia non revisionata. |
| Alta | Il controllore da terminale legge un geofence locale fisso, ma non rileva ostacoli e non ha feedback di velocità/ruota. | Il prototipo non dimostra ancora contenimento affidabile sul campo o arresto prima di urti; velocità effettiva e inerzia restano da misurare. | Validare confine e arresto sul veicolo; progettare percezione ridondante, odometria e controllo ad anello chiuso prima della modalità autonoma operativa. |
| Alta | `mission_name` è convalidato per caratteri e lunghezza, ma il salvataggio usa un timestamp in secondi e `open(..., "w")`. | Due salvataggi con lo stesso nome nello stesso secondo possono sovrascrivere un JSON. | Usare un identificatore univoco e creazione esclusiva o salvataggio atomico; limitare i permessi della cartella. |
| Media | Errori e eccezioni vengono spesso ignorati; stato globale e scritture non sono gestiti per client concorrenti. | Guasti hardware o input malformati possono apparire come telemetria congelata; race e file missione persi/corrotti. | Logging strutturato, watchdog dei sensori, validazione messaggi, stato concorrente protetto, limiti e gestione atomica dei file. |
| Media | Dipendenze frontend caricate da CDN; stream separato senza TLS dichiarato. | Dipendenza di rete e rischio di integrità/privacy se usato su rete non fidata. | Versioni fissate e asset controllati localmente; HTTPS/WSS end-to-end e policy di sicurezza browser. |

## Interfaccia tastiera e controlli rapidi

In `static/autopilota.html`, i comandi WASD e frecce sono ignorati quando il focus è in un campo `input`, `textarea`, `select` o in un elemento modificabile. Questo permette di scrivere il nome del filare in **Registra traccia filare** senza inviare comandi ai motori. Per guidare da tastiera, il focus deve essere fuori dai controlli di testo.

Il pulsante **E-STOP** nell'angolo inferiore richiama `triggerStop()`, la stessa funzione del pulsante **STOP** sul tastierino. Entrambi sono stop software via WebSocket, non arresti di emergenza indipendenti.

Il pulsante etichettato **MOTORI ARMATI** commuta `dry_run`. In modalità simulazione il server non inoltra i comandi al driver motori. Nessuno dei due pulsanti sostituisce un arresto fisico indipendente.

## Decisione tecnica

Non abilitare taglio autonomo né prove con lama attiva basandosi sul repository attuale. Le prove attuali vanno limitate a banco o teleoperazione sorvegliata, ruote sollevate/area protetta e attrezzo di taglio fisicamente disconnesso, finché non esiste una valutazione dei rischi e una catena di sicurezza indipendente.

