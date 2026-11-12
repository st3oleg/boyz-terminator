# Analisi del codice e dello storico

## Perimetro esaminato

Nel repository sono presenti `telemetry_server.py`, `modules/gps.py`, `modules/imu.py`, `modules/motor.py`, quattro script in `tests/` e tre pagine HTML in `static/`. Non sono presenti moduli di navigazione autonoma, configurazione NTRIP/RTCM, pianificazione del taglio, batteria/BMS, controllo lame, geofence o una macchina a stati di sicurezza. I file in `tests/` sono in gran parte programmi dimostrativi con accesso diretto all'hardware, non una suite di test automatizzata.

## Funzionalità effettivamente presenti

| Componente | Comportamento osservato | Limite rilevante |
|---|---|---|
| `telemetry_server.py` | Server aiohttp su porta 8080; WebSocket `/ws`; telemetria GPS/IMU a 5 Hz; comandi per incrementare/decrementare i due motori; watchdog software da 1 s; registrazione JSON di punti GPS; avvio di `ustreamer` su 8081. | Nessuna autenticazione o autorizzazione; comandi e video sono esposti su tutte le interfacce; la registrazione non è subordinata a RTK FIX o freschezza del dato; nessuna guida autonoma. |
| `modules/gps.py` | Parsing di GGA/RMC NMEA su seriale, stato qualità GGA, numero satelliti, altitudine, velocità e heading RMC. | Non verifica checksum né età massima dei dati; eccezioni di parsing possono scartare silenziosamente dati; non configura né riceve correzioni RTK. |
| `modules/imu.py` | Lettura del frame angolare `0x55 0x53` da UART e decodifica roll/pitch/yaw. | Nessuna verifica checksum/frame completo, calibrazione, diagnostica di deriva o uso nel controllo; heading non equivale automaticamente a direzione di marcia affidabile. |
| `modules/motor.py` | Segnali servo a 50 Hz, 1000–2000 µs mappati linearmente a -100…100%; controllo differenziale. | Nessun feedback encoder/velocità, limiti di accelerazione, diagnostica di guasto o arresto hardware. Il valore neutro PWM non prova che il veicolo si arresti in ogni guasto. |
| `static/autopilota.html` | Interfaccia video, telemetria, joystick/tasti, selettore dry-run e registrazione. | “Autopilota” è il nome della pagina: il client invia comandi manuali incrementali; lo slider invia `set_speed`, non gestito dal server. Non c'è esecuzione automatica della traccia. |
| `tests/test_lidar.py`, `tests/test_camera.py` | Prototipi autonomi per visualizzare dati LiDAR e streaming camere. | Non sono integrati come supervisione di sicurezza del rover; un sensore mostrato in una pagina non costituisce una protezione validata. |

### Flusso di comando attuale

La pagina web si collega al WebSocket e invia `motor_step`; il server traduce i tasti in gradini da 10% (primo gradino 20%). Un heartbeat della pagina ogni 800 ms rinnova il watchdog. Quando il watchdog scade, `stop_all_motors()` porta i comandi a zero. Questa è una protezione contro alcune perdite di connessione, non un arresto di emergenza certificabile: dipende dallo stesso processo Linux, dalla stessa rete e dalla stessa elettronica che comandano il veicolo.

Il messaggio `estop` è solo un comando WebSocket; non è collegato a un circuito di emergenza fisico indipendente. Inoltre il server non comanda un apparato di taglio: lo stop software oggi può fermare le ruote comandate, non una lama che non è rappresentata nel progetto.

## Discrepanze con `Storico Google.md`

Lo storico è una raccolta di snapshot, script e requisiti desiderati, non una specifica coerente dell'implementazione corrente. In particolare:

- lo storico parla di waypoint, ritorno a casa, PID, encoder, batteria/BMS, geofence, rilevamento ostacoli e NTRIP: non ho trovato queste funzioni nei file correnti;
- lo storico propone LC29H a 460800 baud, mentre `modules/gps.py` e il server impostano 115200;
- lo storico nomina una MPU-6050 su I²C, mentre il codice presente legge una WT61/seriale `/dev/ttyAMA4`;
- gli script `test_record_gps.py` e `test_lidar.py` sono progetti/prototipi autonomi e non sono chiamati dal server;
- i punti del registratore integrato nel server vengono acquisiti ogni 0,2 s con soglia di 0,25 m e senza filtro sulla qualità RTK; il registratore separato nello storico ha regole diverse. Non sono intercambiabili;
- lo storico contiene comandi distruttivi di terminazione forzata dei processi e istruzioni di avvio per host diversi. Sono stati letti come testo di riferimento e non eseguiti.

Prima di usare lo storico come fonte tecnica, occorre verificare sul rover reale modello, cablaggi, baud rate, porte seriali, driver e firmware GNSS.

## Vulnerabilità e guasti prioritari

Classificazione qualitativa: **Critica** significa che può consentire il movimento non autorizzato o non controllato; **Alta** può rendere la navigazione o il controllo non affidabili; **Media** può compromettere dati o disponibilità.

| Priorità | Rilievo | Conseguenza plausibile | Mitigazione richiesta |
|---|---|---|---|
| Critica | WebSocket senza autenticazione, su `0.0.0.0:8080`, in chiaro se servito via HTTP; stream `ustreamer` su `0.0.0.0:8081`. | Un host raggiungibile può inviare comandi motore, cambiare dry-run, avviare/fermare registrazioni o vedere il video. | Isolare la rete; autenticazione e autorizzazione robuste; TLS; allowlist/origin e protezione CSRF dove applicabile; video protetto; firewall e credenziali gestite fuori dal codice. Non esporre direttamente a Internet. |
| Critica | Nessuna separazione fra teleoperazione e comando di sicurezza; heartbeat condiviso tra tutti i client e rinnovato anche senza comando di guida. | Un client inatteso può tenere vivo il watchdog; più client possono contendersi comando e dry-run. Il watchdog non è un dead-man switch tenuto dall'operatore. | Un solo controllore autorizzato con lease; comando di marcia valido solo con dead-man esplicito; timeout indipendente e hardware che disabilita coppia/attrezzo; pulsanti fisici a bordo e stop remoto verificato. |
| Alta | GPS obsoleto resta disponibile; `last_update` viene aggiornato dalla GGA anche con fix scadente e non viene usato dal server per bloccare comandi/registrazione. | La UI o il registratore possono trattare coordinate vecchie o non RTK come attuali; errore di percorso vicino a persone, filari o confini. | Stato “dato non valido/stale”; soglie su età, qualità, deviazione e integrità; arresto/pausa automatica alla perdita del requisito RTK; seconda modalità di localizzazione validata. |
| Alta | La registrazione integrata accetta coordinate non nulle senza controllare `rtk_status`, precisione o freschezza; non filtra salti/spike. | Traccia contaminata che, se usata in futuro come percorso, codifica errori GPS nel lavoro. | Regole di acquisizione esplicite, qualità per punto, controllo outlier, validazione geometrica e revisione sul campo. La traccia non va eseguita automaticamente. |
| Alta | Nessun controllore autonomo, geofence, rilevamento ostacoli integrato o feedback di velocità/ruota. | Il prototipo non può dimostrare copertura o arresto prima di urti; velocità effettiva e inerzia sono ignote. | Progettare percezione ridondante, odometria, controllo closed-loop, limiti di velocità/spazio e prove di arresto prima della modalità automatica. |
| Alta | `mission_name` viene usato nella composizione del percorso file senza convalida. | Un client non autorizzato può influire sul nome/percorso del JSON; input con separatori può causare scritture fuori dalla cartella missioni se il percorso risultante è valido. | Generare nomi file lato server con ID sicuri; rifiutare separatori e normalizzare/verificare il percorso risultante; limiti di dimensione e permessi minimi. |
| Media | Errori e eccezioni vengono spesso ignorati; stato globale e scritture non sono gestiti per client concorrenti. | Guasti hardware o input malformati possono apparire come telemetria congelata; race e file missione persi/corrotti. | Logging strutturato, watchdog dei sensori, validazione messaggi, stato concorrente protetto, limiti e gestione atomica dei file. |
| Media | Dipendenze frontend caricate da CDN; stream separato senza TLS dichiarato. | Dipendenza di rete e rischio di integrità/privacy se usato su rete non fidata. | Versioni fissate e asset controllati localmente; HTTPS/WSS end-to-end e policy di sicurezza browser. |

## Decisione tecnica

Non abilitare taglio autonomo né prove con lama attiva basandosi sul repository attuale. Le prove attuali vanno limitate a banco o teleoperazione sorvegliata, ruote sollevate/area protetta e attrezzo di taglio fisicamente disconnesso, finché non esiste una valutazione dei rischi e una catena di sicurezza indipendente.

