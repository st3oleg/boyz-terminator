# Riproduzione traccia: stato e criteri di abilitazione

**Aggiornato il 24 novembre 2026.** La pagina web mostra l'anteprima. Il controllore da terminale esegue una tratta in avanti con supervisione e può raccordarsi alla partenza da una posa di riferimento. Sul Raspberry è stato osservato un avvio con GNSS FIX, RTCM connesso e IMU attiva, seguito dall'arresto prima della trazione perché il Rover era a più di 0,5 m dalla partenza. Il raccordo automatico è stato verificato in simulazione. La sua installazione e il completamento di una corsa in campo non sono confermati.

La pagina `riproduzione.html` è separata da `autopilota.html`, che resta la postazione di teleoperazione e registrazione. La pagina nuova elenca le missioni sul Rover, legge il geofence selezionato in `index.html` nello stesso browser e indirizzo, chiede al server di validare la traccia e mostra l'anteprima live. In `index.html` un clic sul poligono lo seleziona e lo evidenzia in arancione; se esiste una sola area, viene selezionata automaticamente. La selezione viene salvata insieme ai poligoni nel browser. Se cambia durante l'anteprima, occorre validare nuovamente la traccia. Non è una configurazione geofence persistita sul Rover. La pagina non contiene un comando di partenza. I motori non ricevono comandi dalla funzione di riproduzione.

## Storico dal Rover e dal PC

Per una nuova traccia, dalla pagina **Autopilota** assegnare un nome alla missione, premere **REC FILARE** e guidare manualmente. A fine passaggio premere **STOP**, poi **SALVA TRACCIA**. Verificare il nome e il numero di punti nella conferma del salvataggio. Per misurare la deriva usare un tratto in avanti e conservare una missione per ogni configurazione di trim.

La sezione **Storico delle tracce** mostra le missioni della cartella `missions/` del Rover con data, numero di punti e presenza di campioni motore. Selezionando una missione, il server ne invia il JSON completo in sola lettura. La pagina disegna la forma della traccia, mostra qualità GNSS, lunghezza indicativa, tabella dei punti e JSON originale; **Scarica copia JSON** salva una copia sul PC. La lettura dello storico e la visualizzazione non avviano i motori.

In alternativa, da PowerShell aperto nella radice del progetto sul PC, con l'alias SSH `Terminator-Tailscale` configurato, copiare le tre missioni delle prove del 23 novembre:

```powershell
$dest = Join-Path (Get-Location) 'tracce-prova'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
scp 'Terminator-Tailscale:/home/terminator/Documents/missions/avantiDritto1_1795443165.json' $dest
scp 'Terminator-Tailscale:/home/terminator/Documents/missions/avantiDrittoTrim10sx_1795443244.json' $dest
scp 'Terminator-Tailscale:/home/terminator/Documents/missions/MappaComandoGiusta_1795443596.json' $dest
Get-ChildItem -LiteralPath $dest -Filter '*.json' | Select-Object Name,Length
```

Per copiare missioni nuove, sostituire i nomi con quelli riportati dalla conferma di salvataggio. Nella sessione del 23 novembre tutti e tre i trasferimenti sono riusciti. Il [resoconto di calibrazione](calibrazione-motori-e-tracce.md#prove-manuali-del-23-novembre-2026) riporta i valori di trim, il numero di punti e i limiti delle misure.

Sul PC usare **Tracce dal PC** per selezionare uno o più JSON, oppure **Scegli una cartella del PC** per selezionare la cartella `missions`: la pagina aggiunge i JSON trovati in **Registrazioni disponibili**. I file restano locali durante la visualizzazione. Al clic su **Valida la traccia selezionata e mostra anteprima live**, il JSON viene inviato in memoria al Rover per l'anteprima.

La pagina funziona anche aperta come `file:///.../static/riproduzione.html`: in questo caso occorre indicare l'indirizzo del Rover, per esempio `http://terminator.local:8080` oppure il suo IP. La comunicazione con il Rover usa il WebSocket `/ws`. Il geofence salvato nella Mappa Live è condiviso automaticamente solo se Mappa e Riproduzione sono aperte nello stesso browser **e nella stessa origine**; `file:///` e `http://terminator.local:8080` non condividono l'archivio del browser. Per usare la selezione della Mappa, aprire entrambe le pagine dall'indirizzo del Rover. In alternativa, la pagina locale permette di importare il GeoJSON del geofence dal PC per la sola anteprima.

## Disegnare e salvare il geofence

Nella sezione 2 di Riproduzione si può disegnare un singolo poligono sulla mappa satellitare, modificare i vertici, rimuoverlo, importare un `.geojson`/`.json` o tornare al poligono selezionato in Mappa Live. La traccia selezionata è sovrapposta alla mappa. Se non si dispone di un file, basta disegnare il poligono; i file esportati dalla pagina Rilievo e quelli già salvati in `Geofencing` sono importabili.

La cartella del progetto `Geofencing/` è stata creata. **Salva sul PC in Geofencing** usa il selettore di cartella del browser: scegliere `boyz-terminator-main` oppure `Geofencing`; il file viene scritto nella sottocartella `Geofencing`. Nei browser senza accesso diretto alle cartelle, la pagina scarica il GeoJSON e indica di spostarlo manualmente in `Geofencing`. **Salva sul Rover in Geofencing** invia il poligono al server, che lo valida e salva in `/home/terminator/Documents/Geofencing/`; l'elenco permette poi di riaprirlo. Questa configurazione resta un'anteprima: il file salvato non abilita il movimento automatico.

`modules/route_replay.py` verifica che la missione abbia almeno due posizioni distinte, punti RTK FIX, timestamp crescenti quando presenti, nessun salto maggiore di 5 m fra campioni e un percorso interamente dentro un singolo poligono GeoJSON con margine iniziale di 0,75 m dal bordo. Il margine è riferito alla posizione del ricevitore/centro, non all'ingombro completo del rover. La geometria del poligono va ancora verificata sul campo; non basta il dato salvato nel browser per autorizzare il movimento.

Il loop del server aggiorna l'anteprima a 5 Hz. Rifiuta posizione senza FIX o più vecchia di 1,5 s, correzioni RTCM disconnesse o più vecchie di 3 s, posizione fuori geofence, errore laterale oltre 0,8 m, meta entro 0,5 m e bersaglio dietro al Rover. L'anteprima utilizza la direzione GNSS quando la velocità è almeno 1,8 km/h e il dato ha al massimo 1,5 s. Può mostrare **Orientamento indisponibile** da fermo. L'inizializzazione dello yaw descritta sotto appartiene al controllore da terminale.

`MotorCalibration` trasforma velocità richieste e curvatura in percentuali SX/DX usando due curve e una rampa. Il controllore da terminale carica i valori sperimentali di `profilo_guida.json` e rifiuta velocità oltre gli intervalli misurati. Le misure e il metodo sono nella [guida di calibrazione](calibrazione-motori-e-tracce.md#misure-con-le-ruote-riparate).

## Stato del collaudo sul Rover

1. **Trazione e arresto.** L'operatore ha riparato le ruote e ha riferito tre prove del pulsante d'arresto fisico. Le registrazioni in avanti dopo la riparazione forniscono un primo profilo PWM.
2. **Geofence.** La missione scelta è stata validata con `GeofenceTOTALEprove.geojson`. Il controllore legge il file a bordo. Il margine di 2 m del profilo sperimentale va verificato rispetto all'ingombro del Rover e alla distanza di arresto sul fondo di prova.
3. **Esito reale noto.** Il Raspberry ha caricato la missione, ricevuto FIX, RTCM e IMU e restituito `STOP: Posiziona il rover entro 0,5 m dalla partenza`. Il log disponibile in chat documenta l'arresto preliminare.
4. **Da verificare in campo.** Completamento di raccordo e andata, errore laterale e distanza di arresto misurati, comportamento alla perdita di posa o controllo. Il monitor ostacoli a bordo non è integrato. Il collaudo da terminale è supervisionato, in area libera e con apparato di taglio scollegato.

I limiti numerici dell'anteprima sono valori iniziali conservativi per individuare dati incoerenti: non sono ancora soglie validate per questo telaio o questo vigneto.

## Prima prova di Pure Pursuit

Webots, l'anteprima del Rover e il controllore da terminale condividono `modules/pure_pursuit.py`, che calcola il punto da inseguire e la curvatura. Il controllore legge `GeofenceTOTALEprove.geojson`, interpola il profilo PWM e passa i comandi a `MotorDriver`. La missione predefinita è `avantiDritto1_sola_andata_1795443165.json` da 17,86 m. Per la prova attuale si seleziona `MappaComandoGiusta_1795443596.json` dal punto 1 al **46**, il più lontano dalla partenza, per **33,80 m**. L'andata viene percorsa in avanti. La corsa termina al punto 46.

Nel modello con driver simulato l'andata di 33,80 m è terminata in circa 127 s. Partendo dalla posa finale della registrazione `50trattino50_1795449400.json`, il pianificatore ha trovato un raccordo di 21,9 m. Nello stesso modello, raccordo e andata sono terminati in circa 209 s, con errore laterale massimo di circa 0,28 m e comandi finali SX/DX a zero. Questi numeri sono risultati di simulazione.

Per la partenza manuale l'operatore allinea il Rover al primo tratto. Il controllore usa la direzione iniziale della traccia e aggiorna lo yaw dalle variazioni IMU. Il raccordo invece stima lo yaw iniziale dalla registrazione di riferimento e confronta la direzione stimata con lo spostamento GNSS durante l'avvicinamento.

Il monitor ostacoli a bordo è attualmente indisponibile. Il controllore da terminale è destinato al collaudo con presenza continua dell'operatore e arresto fisico indipendente funzionante. L'anteprima web conserva il suo blocco. Il programma da terminale termina e porta i comandi a zero quando l'operatore rilascia Spazio, preme Q o quando un controllo fallisce. Un blocco del processo Python richiede l'intervento dell'arresto fisico.

### Controllore locale sul Raspberry

`python3 -m modules.follow_route` valida traccia e geofence dalla radice del progetto senza inizializzare l'hardware. Per l'esecuzione supervisionata il parametro `--profile` richiede un JSON locale con i valori misurati di `imu_yaw_sign`, `cruise_mps`, `max_speed_mps`, `clearance_m` e `motor_calibration` (`track_width_m`, `left_curve`, `right_curve`, `max_pct`, `ramp_pct_per_s`). Le curve SX e DX contengono coppie `[m/s, percentuale PWM]` a partire da `[0, 0]`. Il limite è 50% per lato. Il profilo richiede inoltre le conferme `wheels_verified` e `physical_estop_verified`. Non usare le misure ottenute con i copertoni che slittano sul cerchione.

Per aggiornare il raccordo, copiare `modules/follow_route.py` in `/home/terminator/Documents/modules/` dal PC. Il Rover deve avere anche `modules/route_replay.py` aggiornato, `profilo_guida.json` nella radice, i due JSON di missione e riferimento in `missions/` e il geofence in `Geofencing/`.

Per validare i file senza inizializzare l'hardware, dal terminale del Raspberry eseguire:

```bash
cd /home/terminator/Documents
python3 -m modules.follow_route --mission MappaComandoGiusta_1795443596.json --until-sample 46 --approach-reference 50trattino50_1795449400.json
```

Prima del collaudo fermare il server di teleoperazione per liberare GPS, IMU e GPIO. Con il Rover sorvegliato e l'area libera, nello stesso terminale eseguire:

```bash
cd /home/terminator/Documents
BASE_TAILSCALE_HOST=100.85.248.82 BASE_RTCM_PORT=5000 \
python3 -m modules.follow_route \
  --mission MappaComandoGiusta_1795443596.json \
  --until-sample 46 \
  --approach-reference 50trattino50_1795449400.json \
  --profile profilo_guida.json \
  --log "replay-raccordo-$(date +%Y%m%d-%H%M%S).jsonl"
```

Dopo **GNSS FIX**, **RTCM connesso** e **IMU attiva**, tenere premuto **Spazio**. La corsa termina premendo **Q**, rilasciando Spazio per più di circa 0,8 s, alla meta o su un controllo fallito. Per ogni corsa usare un nuovo file `--log`. Il JSONL registra la fase (`raccordo` o `traccia`), curvatura, distanze, comandi SX/DX e motivo dell'arresto.

`--approach-reference` richiede una registrazione in avanti a comando stabile e una posa finale ferma con FIX. Usare una registrazione della sessione corrente, con il Rover ancora nella posa finale. Il programma richiede accordo entro **0,5 m** e **8°** con quella posa, partenza della missione entro **25 m** e raccordo compatibile con il geofence e la curvatura ammessa. Se mostra **Posa attuale diversa dalla fine della registrazione di riferimento**, acquisire un riferimento valido per la posa attuale oppure riportare il Rover a mano alla partenza e avviare la missione allineata senza `--approach-reference`.
