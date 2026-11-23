# Riproduzione traccia: stato e criteri di abilitazione

**Aggiornato il 23 novembre 2026.** Registrazione manuale e copia dei JSON dal Rover al PC confermate. La pagina web resta un'anteprima. Il controllore sperimentale da terminale è disponibile nel codice locale e attende la verifica sul Rover fisico.

La pagina `riproduzione.html` è separata da `autopilota.html`, che resta la postazione di teleoperazione e registrazione. La pagina nuova elenca le missioni sul Rover, legge il geofence selezionato in `index.html` nello stesso browser e indirizzo, chiede al server di validare la traccia e mostra l'anteprima live. In `index.html` un clic sul poligono lo seleziona e lo evidenzia in arancione; se esiste una sola area, viene selezionata automaticamente. La selezione viene salvata insieme ai poligoni nel browser. Se cambia durante l'anteprima, occorre validare nuovamente la traccia. Non è una configurazione geofence persistita sul Rover. La pagina non contiene un comando di partenza. I motori non ricevono comandi dalla funzione di riproduzione.

## Storico dal Rover e dal PC

Per una nuova traccia, dalla pagina **Autopilota** assegnare un nome alla missione, premere **REC FILARE** e guidare manualmente. A fine passaggio premere **STOP**, poi **SALVA TRACCIA**. Verificare il nome e il numero di punti nella conferma del salvataggio. Per misurare la deriva usare un tratto in avanti e conservare una missione per ogni configurazione di trim.

La sezione **Storico delle tracce** mostra le missioni della cartella `missions/` del Rover con data, numero di punti e presenza di campioni motore. Selezionando una missione, il server ne invia il JSON completo in sola lettura. La pagina disegna la forma della traccia, mostra qualità GNSS, lunghezza indicativa, tabella dei punti e JSON originale; **Scarica copia JSON** salva una copia sul PC. La lettura dello storico e la visualizzazione non avviano i motori.

In alternativa, da PowerShell sul PC, con l'alias SSH `Terminator-Tailscale` configurato, copiare le tre missioni delle prove del 23 novembre:

```powershell
$dest = Join-Path $env:USERPROFILE 'Downloads\boyz-terminator-main\tracce-prova'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
scp 'Terminator-Tailscale:/home/terminator/Documents/missions/avantiDritto1_1795443165.json' $dest
scp 'Terminator-Tailscale:/home/terminator/Documents/missions/avantiDrittoTrim10sx_1795443244.json' $dest
scp 'Terminator-Tailscale:/home/terminator/Documents/missions/MappaComandoGiusta_1795443596.json' $dest
Get-ChildItem -LiteralPath $dest -Filter '*.json' | Select-Object Name,Length
```

Per copiare missioni nuove, sostituire i nomi con quelli riportati dalla conferma di salvataggio. Nella sessione del 23 novembre tutti e tre i trasferimenti sono riusciti. Il [resoconto di calibrazione](calibrazione-motori-e-tracce.md#prove-manuali-del-23-novembre-2026) riporta i valori di trim, il numero di punti e i limiti delle misure.

Sul PC si possono scegliere più file JSON o una cartella con il selettore del browser. Il browser non può leggere automaticamente l'intero disco: solo i file selezionati dall'utente vengono aperti. I file del PC restano locali durante la visualizzazione; se si preme **Valida**, il JSON viene inviato in memoria al Rover per l'anteprima, senza salvarlo in `missions/`.

La pagina funziona anche aperta come `file:///.../static/riproduzione.html`: in questo caso occorre indicare l'indirizzo del Rover, per esempio `http://terminator.local:8080` oppure il suo IP. La comunicazione con il Rover usa il WebSocket `/ws`. Il geofence salvato nella Mappa Live è condiviso automaticamente solo se Mappa e Riproduzione sono aperte nello stesso browser **e nella stessa origine**; `file:///` e `http://terminator.local:8080` non condividono l'archivio del browser. Per usare la selezione della Mappa, aprire entrambe le pagine dall'indirizzo del Rover. In alternativa, la pagina locale permette di importare il GeoJSON del geofence dal PC per la sola anteprima.

## Disegnare e salvare il geofence

Nella sezione 2 di Riproduzione si può disegnare un singolo poligono sulla mappa satellitare, modificare i vertici, rimuoverlo, importare un `.geojson`/`.json` o tornare al poligono selezionato in Mappa Live. La traccia selezionata è sovrapposta alla mappa. Se non si dispone di un file, basta disegnare il poligono; i file esportati dalla pagina Rilievo e quelli già salvati in `Geofencing` sono importabili.

La cartella del progetto `Geofencing/` è stata creata. **Salva sul PC in Geofencing** usa il selettore di cartella del browser: scegliere `boyz-terminator-main` oppure `Geofencing`; il file viene scritto nella sottocartella `Geofencing`. Nei browser senza accesso diretto alle cartelle, la pagina scarica il GeoJSON e indica di spostarlo manualmente in `Geofencing`. **Salva sul Rover in Geofencing** invia il poligono al server, che lo valida e salva in `/home/terminator/Documents/Geofencing/`; l'elenco permette poi di riaprirlo. Questa configurazione resta un'anteprima: il file salvato non abilita il movimento automatico.

`modules/route_replay.py` verifica che la missione abbia almeno due posizioni distinte, punti RTK FIX, timestamp crescenti quando presenti, nessun salto maggiore di 5 m fra campioni e un percorso interamente dentro un singolo poligono GeoJSON con margine iniziale di 0,75 m dal bordo. Il margine è riferito alla posizione del ricevitore/centro, non all'ingombro completo del rover. La geometria del poligono va ancora verificata sul campo; non basta il dato salvato nel browser per autorizzare il movimento.

Il loop del server aggiorna l'anteprima a 5 Hz. Rifiuta posizione senza FIX o più vecchia di 1,5 s, correzioni RTCM più vecchie di 3 s, posizione fuori geofence, errore laterale oltre 0,8 m, meta entro 0,5 m e target dietro al rover. Usa il course GNSS solo in movimento (almeno 1,8 km/h) e se aggiornato entro 1,5 s; sotto tale velocità richiede una IMU recente e un offset/verso calibrati. Non è ancora presente una calibrazione di yaw per il Rover, perciò la posa può essere indisponibile da fermo. Il parser GNSS ora registra il tempo dell'ultimo RMC per distinguere un course vecchio da uno recente.

`MotorCalibration` trasforma velocità ruota richieste e curvatura in percentuali nominali SX/DX tramite due curve misurate e una rampa. È codice passivo e rifiuta extrapolazioni oltre le misure: i parametri non sono ancora disponibili. Il CSV di `tools/analyze_motor_calibration.py` sarà il punto di partenza per rivedere e costruire queste curve dopo la prova rettilinea, includendo differenze fra le due ruote. Il trim esistente resta applicato al confine del driver.

## Cosa manca prima del movimento automatico

1. Sostituire le ruote con cui è stato osservato slittamento tra copertone e cerchione e verificare la trazione sul fondo di prova. Misurare la risposta ai comandi SX/DX con le ruote nuove e definire carreggiata effettiva, accelerazione, decelerazione, velocità massima e comportamento in curva. Usare parametri misurati sul telaio reale.
2. Calibrare il verso e l'offset della IMU e verificare la coerenza GNSS/IMU, specialmente a bassa velocità e all'avvio. Il GNSS a 1 Hz e il course over ground da soli non danno un heading affidabile da fermo.
3. Installare un monitor ostacoli sul Rover che produca una misura fresca e verificata. Al momento i prototipi LiDAR/camera non alimentano il controllo: il gate ostacoli resta intenzionalmente chiuso.
4. Portare il geofence verificato in una configurazione locale del Rover, validare poligono, margini, ingombro e distanza di arresto, e bloccare il movimento se manca. La copia inviata dal browser serve solo per l'anteprima.
5. Verificare l'integrazione del controllore da terminale con gli attuatori reali, le cause di stop registrate e l'arresto fisico indipendente da Python.
6. Verificare con test progressivi: simulazione, ruote sollevate, area libera con apparato di taglio disconnesso, poi prove ripetute con metriche di errore laterale e distanza di arresto. Il semplice arrivo alla meta non misura affidabilità né sicurezza.

I limiti numerici dell'anteprima sono valori iniziali conservativi per individuare dati incoerenti: non sono ancora soglie validate per questo telaio o questo vigneto.

## Prima prova di Pure Pursuit

Webots, l'anteprima del Rover e il controllore da terminale condividono `modules/pure_pursuit.py`, che calcola il punto da inseguire e la curvatura. Il controllore carica la sola andata `avantiDritto1_sola_andata_1795443165.json` e `GeofenceTOTALEprove.geojson` dai file a bordo. Converte la curvatura in PWM usando la calibrazione per lato e passa i comandi a `MotorDriver`.

Per provare la geometria in simulazione si può usare la sola andata della traccia a trim zero. Il controllore cercherà di seguire la curva registrata. Per il primo test di marcia rettilinea sul Rover, dopo la sostituzione delle ruote e le verifiche sopra, usare una retta di riferimento tra due punti e una sola andata a bassa velocità. Partire allineati alla retta e misurare errore laterale e arresto. Tenere separata la retromarcia per evitare di confondere direzione di spostamento e orientamento del muso all'inversione.

La simulazione e l'anteprima sono disponibili durante il lavoro sulle ruote. Per il collaudo in piazzale l'operatore allinea il Rover alla partenza e sorveglia l'area. Alla partenza il controllore usa la direzione iniziale della traccia e aggiorna lo yaw dalle variazioni IMU. Confronta la direzione GNSS quando la velocità e la freschezza del dato lo consentono.

Il monitor ostacoli a bordo è attualmente indisponibile. Il controllore da terminale è destinato al collaudo con presenza continua dell'operatore e arresto fisico indipendente funzionante. L'anteprima web conserva il suo blocco. Il programma da terminale termina e porta i comandi a zero quando l'operatore rilascia Spazio, preme Q o quando un controllo fallisce. Un blocco del processo Python richiede l'intervento dell'arresto fisico.

### Controllore locale sul Raspberry

`python3 -m modules.follow_route` valida traccia e geofence dalla radice del progetto senza inizializzare l'hardware. Per l'esecuzione supervisionata il parametro `--profile` richiede un JSON locale con i valori misurati di `imu_yaw_sign`, `cruise_mps`, `max_speed_mps`, `clearance_m` e `motor_calibration` (`track_width_m`, `left_curve`, `right_curve`, `max_pct`, `ramp_pct_per_s`). Le curve SX e DX contengono coppie `[m/s, percentuale PWM]` a partire da `[0, 0]`. Il limite è 50% per lato. Il profilo richiede inoltre le conferme `wheels_verified` e `physical_estop_verified`. Non usare le misure ottenute con i copertoni che slittano sul cerchione.

Prima di un collaudo con l'hardware funzionante, fermare il servizio di teleoperazione perché il controllore usa direttamente GPS, IMU e GPIO. Configurare `BASE_TAILSCALE_HOST` come per il server, usare un terminale supervisionato e indicare un file nuovo per `--log` a ogni esecuzione. Il log JSONL contiene curvatura, permessi di posa, PWM SX/DX e causa di arresto. La configurazione di trazione misurata per il Rover non è ancora disponibile.
