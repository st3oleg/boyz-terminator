# Analisi del codice e dello storico

**Stato aggiornato:** 19 novembre 2026. Le note descrivono il checkout locale; i cambiamenti recenti non sono ancora stati verificati/installati sul Rover.

## Perimetro esaminato

Nel repository sono presenti `telemetry_server.py`, i moduli GPS/IMU/motori, client Rover RTCM/TCP, geometria Pure Pursuit, script e pagine HTML. L'`index` offre una UI per disegnare e modificare perimetri GeoJSON salvati nel `localStorage` del browser; questa configurazione non è trasmessa al controllore e non limita il movimento. È presente il trasporto RTCM su TCP privato e la scrittura seriale al ricevitore; non è un servizio NTRIP. `modules/pure_pursuit.py` calcola target e curvatura, ma non è collegato al loop motori. I file in `tests/` sono in gran parte programmi dimostrativi con accesso diretto all'hardware, non una suite di test automatizzata.

## Funzionalità effettivamente presenti

| Componente | Comportamento osservato | Limite rilevante |
|---|---|---|
| `telemetry_server.py` | Server aiohttp su porta 8080; WebSocket `/ws`; telemetria GPS/IMU a 5 Hz; comandi motori; watchdog software da 1 s; client RTCM/TCP opzionale; registrazione JSON versione 3 a ogni nuovo GGA (normalmente 1 Hz), con campi motore e diagnostica. Applica e salva il trim differenziale prima del driver. | Nessuna autenticazione/autorizzazione; servizi esposti sulle interfacce configurate; nessun loop Pure Pursuit integrato agli attuatori né sicurezza indipendente. La registrazione ammette qualità diverse da FIX, sempre indicate punto per punto. |
| `modules/gps.py` | Parsing di GGA/RMC NMEA, qualità GGA, satelliti, altitudine, velocità e heading; scrittura RTCM tramite lo stesso proprietario seriale. | Non verifica checksum; il parser non costituisce una garanzia di integrità assoluta; l'uscita FIX va validata per freschezza e uso in movimento. |
| `modules/imu.py` | Lettura del frame angolare `0x55 0x53` da UART e decodifica roll/pitch/yaw. | Nessuna verifica checksum/frame completo, calibrazione, diagnostica di deriva o uso nel controllo; heading non equivale automaticamente a direzione di marcia affidabile. |
| `modules/motor.py` | Segnali servo a 50 Hz, 1000–2000 µs mappati linearmente a -100…100%; controllo differenziale. | Nessun feedback encoder/velocità, limiti di accelerazione, diagnostica di guasto o arresto hardware. Il valore neutro PWM non prova che il veicolo si arresti in ogni guasto. |
| `static/autopilota.html` | Interfaccia video, telemetria, comandi manuali, selettore dry-run, registrazione e slider trim differenziale. I comandi nominali visualizzati restano distinti dalle percentuali effettive al driver. | “Autopilota” è il nome della pagina: invia ancora comandi manuali incrementali. Non c'è esecuzione automatica della traccia o controllo Pure Pursuit. |
| `static/index.html` | Mappa live Rover/Base e strumenti di disegno, modifica e rimozione dei perimetri autorizzati; i poligoni sono salvati localmente nel browser. | I confini non raggiungono il controllore a bordo e non applicano alcun blocco; Leaflet-Geoman è uno strumento di configurazione UI, non una funzione di sicurezza. |
| `static/scatter_analysis.html` | Accumula i fix GNSS Rover via WebSocket durante l'analisi; evita duplicati tramite timestamp del fix. | Il server attuale pubblica la posizione Base a zero e non fornisce campioni della stazione, quindi l'analisi Base resta vuota. I dati non sono persistiti tra sessioni. |
| `tests/test_lidar.py`, `tests/test_camera.py` | Prototipi autonomi per visualizzare dati LiDAR e streaming camere. | Non sono integrati come supervisione di sicurezza del rover; un sensore mostrato in una pagina non costituisce una protezione validata. |

### Flusso di comando attuale

La pagina web si collega al WebSocket e invia `motor_step`; il server traduce i tasti in gradini da 10% (primo gradino 20%). Un heartbeat della pagina ogni 800 ms rinnova il watchdog. Quando il watchdog scade, `stop_all_motors()` porta i comandi a zero. Questa è una protezione contro alcune perdite di connessione, non un arresto di emergenza certificabile: dipende dallo stesso processo Linux, dalla stessa rete e dalla stessa elettronica che comandano il veicolo.

Il trim applica una correzione relativa a SX/DX al confine del driver e la salva nel file JSON di calibrazione (predefinito `/home/terminator/Documents/motor_calibration.json`). I punti registrano comando nominale, trim, uscita effettiva, PWM, stato GNSS/RTCM, IMU e relative età. Gli eventi motore sono salvati in `diagnostic_events`; sono dati passivi e non entrano nel calcolo dei comandi.

Il messaggio `estop` è solo un comando WebSocket; non è collegato a un circuito di emergenza fisico indipendente. Inoltre il server non comanda un apparato di taglio: lo stop software oggi può fermare le ruote comandate, non una lama che non è rappresentata nel progetto.

## Discrepanze con `Storico Google.md`

Lo storico è una raccolta di snapshot, script e requisiti desiderati, non una specifica coerente dell'implementazione corrente. In particolare:

- lo storico parla di waypoint, ritorno a casa, PID, encoder, batteria/BMS, geofence applicato al movimento, rilevamento ostacoli e NTRIP: nel progetto è ora presente solo l'editor cartografico dei perimetri, non il controllo autonomo o le altre funzioni;
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

## Interfaccia tastiera e controlli rapidi

In `static/autopilota.html`, i comandi WASD e frecce sono ignorati quando il focus è in un campo `input`, `textarea`, `select` o in un elemento modificabile. Questo permette di scrivere il nome del filare in **Registra traccia filare** senza inviare comandi ai motori. Per guidare da tastiera, il focus deve essere fuori dai controlli di testo.

Il pulsante **E-STOP** nell'angolo inferiore richiama `triggerStop()`, la stessa funzione del pulsante **STOP** sul tastierino: è una duplicazione nell'interfaccia e si può rimuovere per semplificare la pagina. Entrambi sono stop software via WebSocket, non arresti di emergenza indipendenti.

Il pulsante etichettato **MOTORI ARMATI** commuta `dry_run`. In modalità simulazione il server non inoltra i comandi al driver motori; il controllo ha quindi un uso pratico e va mantenuto, con un'etichetta più chiara come **SIMULAZIONE** e uno stato ben visibile. Nessuno dei due pulsanti sostituisce un arresto fisico indipendente.
| Alta | I comandi manuali non sono bloccati se GNSS è degradato o obsoleto; il logger filtra i dati più vecchi di 3 s ma registra anche `FLOAT`, `DGPS` e `SINGLE`, oltre a `FIX`. | Operatore o funzione futura possono usare posizione non adeguata alla precisione RTK richiesta; la traccia può contenere qualità diverse. | Mostrare qualità/età chiaramente; imporre requisiti RTK nel futuro controllore autonomo; per analisi di precisione selezionare esplicitamente `FIX`; valutare outlier. |
| Alta | La registrazione conserva qualità e freschezza, ma non applica ancora filtro di salti/spike né verifica la ripetibilità su punti noti. | Una traccia può contenere salti di posizione o errori sistematici che si ripeterebbero nel playback. | Aggiungere controllo outlier, validazione geometrica e prove di accuratezza/ripetibilità; non eseguire automaticamente una traccia non revisionata. |
| Alta | Nessun controllore autonomo, enforcement del geofence a bordo, rilevamento ostacoli integrato o feedback di velocità/ruota. | Il prototipo non può dimostrare contenimento entro i confini, copertura o arresto prima di urti; velocità effettiva e inerzia sono ignote. | Trasferire i confini al controllore locale; progettare percezione ridondante, odometria, controllo closed-loop, limiti di velocità/spazio e prove di arresto prima della modalità automatica. |
| Alta | `mission_name` viene usato nella composizione del percorso file senza convalida. | Un client non autorizzato può influire sul nome/percorso del JSON; input con separatori può causare scritture fuori dalla cartella missioni se il percorso risultante è valido. | Generare nomi file lato server con ID sicuri; rifiutare separatori e normalizzare/verificare il percorso risultante; limiti di dimensione e permessi minimi. |
| Media | Errori e eccezioni vengono spesso ignorati; stato globale e scritture non sono gestiti per client concorrenti. | Guasti hardware o input malformati possono apparire come telemetria congelata; race e file missione persi/corrotti. | Logging strutturato, watchdog dei sensori, validazione messaggi, stato concorrente protetto, limiti e gestione atomica dei file. |
| Media | Dipendenze frontend caricate da CDN; stream separato senza TLS dichiarato. | Dipendenza di rete e rischio di integrità/privacy se usato su rete non fidata. | Versioni fissate e asset controllati localmente; HTTPS/WSS end-to-end e policy di sicurezza browser. |

## Decisione tecnica

Non abilitare taglio autonomo né prove con lama attiva basandosi sul repository attuale. Le prove attuali vanno limitate a banco o teleoperazione sorvegliata, ruote sollevate/area protetta e attrezzo di taglio fisicamente disconnesso, finché non esiste una valutazione dei rischi e una catena di sicurezza indipendente.

