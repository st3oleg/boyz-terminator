# Video, PING della telemetria e rete del Rover

Stato del codice e osservazioni discusse il 23 novembre 2026. Le misure riportate dall'operatore sono indicazioni sul campo, non benchmark ripetuti sul Raspberry.

## Camere e indirizzi

`telemetry_server.py` avvia due EMEET USB con `ustreamer` e la camera CSI con `rpicam-vid` (oppure `libcamera-vid`). Il codice non importa una nuova libreria Python per elaborare i fotogrammi: la CSI è letta come MJPEG dal processo `rpicam-vid`, mentre i preset EMEET sono applicati tramite `v4l2-ctl`. `tests/test_camera.py` è una prova separata che usa la porta `8081`: non avviarla insieme al server di telemetria.

| Camera | Video con RTT HTTP visibile | MJPEG senza interfaccia |
|---|---|---|
| EMEET USB 1 | `http://<IP_DEL_RASPBERRY>:8080/camera/usb1` | `http://<IP_DEL_RASPBERRY>:8081/stream` |
| EMEET USB 2 | `http://<IP_DEL_RASPBERRY>:8080/camera/usb2` | `http://<IP_DEL_RASPBERRY>:8082/stream` |
| CSI | `http://<IP_DEL_RASPBERRY>:8080/camera/csi` | `http://<IP_DEL_RASPBERRY>:8080/camera/csi/stream` |

Il banner nel terminale mostra solo Mappa, Autopilota e le tre pagine **Video + Ping**. Gli URL MJPEG restano disponibili per i client che richiedono il video grezzo. Le pagine video hanno un selettore per le tre camere e un link ad Autopilota.

La CSI può impiegare circa un minuto a mostrare il primo frame: è quanto osservato sul rover. Non dedurre un guasto dal solo messaggio iniziale «Connessione video in corso». Se non parte, controlla il terminale del server e prova la camera separatamente dopo aver arrestato `telemetry_server.py`. La cattura CSI corrente è a 960×540, 10 fps; le due USB sono configurate a 640×480, 15 fps. In Autopilota le miniature delle camere non selezionate si aggiornano ogni 5 secondi. I precedenti pulsanti FPS nella pagina cambiavano soltanto l'indicatore grafico e sono stati rimossi.

Le USB vengono rilevate prima tramite i link `/dev/v4l/by-id/*index0*`, poi tramite `/dev/v4l/by-path` e sysfs. Il numero `/dev/videoN` può cambiare quando si collegano periferiche: per verificare quale EMEET occupa `8081` o `8082`, leggere le righe `[INFO] Camera USB` all'avvio. L'ordine fisico stabile delle due webcam identiche non è stato verificato sul rover in tutte le combinazioni di collegamento.

## Cinque preset EMEET

Il cursore **Immagine** di Autopilota agisce sulle due USB, non sulla CSI. I tre livelli originali sono rimasti invariati; due estremi sono stati aggiunti:

| Livello | Esposizione richiesta (`exposure_time_absolute`) | Gain richiesto |
|---|---:|---:|
| Notturno+ | 600 (60 ms) | 30 |
| Notturno | 250 (25 ms) | 15 |
| Bilanciato | 80 (8 ms) | 0 |
| Diurno | 40 (4 ms) | 0 |
| Sole forte | 5 (0,5 ms) | 0 |

Il server imposta l'esposizione manuale, interroga i limiti V4L2 di **ciascuna** webcam, adatta i valori alla gamma supportata e prova a rileggerli dopo l'applicazione. Il messaggio sotto il cursore mostra i valori letti oppure segnala che la lettura non è disponibile. `Bilanciato` viene applicato all'avvio; il preset salvato nel browser viene reinviato quando Autopilota apre il WebSocket, e poi quando si sposta il cursore. Queste chiamate `v4l2-ctl` non elaborano continuamente i frame. I valori Notturno+ non rappresentano necessariamente il massimo hardware: dipendono dai limiti che il dispositivo dichiara, dal frame rate e dal rumore accettabile.

Una dominante rosa/rossa della **CSI** in piena luce è compatibile con un modulo NoIR, privo di filtro infrarosso; dalla sola immagine non si può confermare il modello. Per colori fedeli di giorno, un modulo NoIR può richiedere un filtro IR-cut. [Raspberry Pi descrive la dominante rosa nelle camere NoIR](https://www.raspberrypi.com/products/pi-noir-camera-v2/).

## Significato dei numeri di latenza

**Conservare questa distinzione nel codice e nell'interfaccia:**

- **PING in Autopilota = età della telemetria WebSocket**, calcolata come `Date.now() - data.timestamp` quando arriva un messaggio `telemetry`. L'operatore ha chiesto esplicitamente di non cambiarne il significato. Il valore comprende ritardo di produzione, accodamento, trasporto e gestione nel browser; dipende anche dalla sincronizzazione degli orologi di browser e rover.
- **RTT nelle pagine camera = Round Trip Time** di una piccola richiesta HTTP dal browser a `/camera/ping` e ritorno. HTTP (*Hypertext Transfer Protocol*) è il protocollo della richiesta, non un'altra misura del tempo. L'RTT non misura il ritardo del fotogramma.
- Il riscontro **INPUT → ROVER** è un'ulteriore misura dei comandi WebSocket e va letto separatamente.

Per questo 200 ms di RTT camera e 1200 ms di PING in Autopilota non sono direttamente confrontabili. Durante la chat sono stati riferiti valori di circa 500–700 ms di PING prima e fino a 1200 ms dopo; la causa non è stata confermata. La CSI e le miniature aggiungono carico di CPU/rete, mentre i nuovi preset aggiungono soprattutto chiamate V4L2 al cambio impostazione o alla connessione. Le riduzioni di traffico sopra descritte non sono ancora state misurate con un confronto controllato sul rover.

Per isolare il problema, annotare nello stesso intervallo: PING di Autopilota, RTT di una pagina camera, camera selezionata, preset, stato della rete e latenza INPUT → ROVER. Confrontare pagina Autopilota aperta/chiusa e, se possibile, hotspot del telefono con un'altra rete. Se cresce solo il PING, controllare anche accodamento WebSocket, carico del server/browser e sincronizzazione oraria; se crescono entrambi, indagare rete e saturazione. Un riavvio completo del rover era previsto, ma il suo esito non è documentato qui.

L'hotspot del telefono può essere influenzato da copertura cellulare, carico, risparmio energetico o temperature anomale. Il ritorno a temperatura normale non è di per sé una causa probabile di peggioramento; caldo e freddo estremi possono invece limitare il telefono. [Indicazioni Google sulla temperatura durante l'hotspot](https://support.google.com/pixelphone/answer/15679416), [indicazioni Apple sulla temperatura](https://support.apple.com/en-us/118431).

## Versioni Git discusse

Il ramo aggiornato è `main`. Nel repository consultato durante la chat, `4109cad` (23 novembre 2026, 10:02 CET) è l'ultimo commit prima dei cinque preset: contiene soltanto Notturno, Bilanciato e Diurno. È una versione di prova storica, precedente anche alle pagine Video + Ping. L'operatore ha poi scelto di tornare al codice aggiornato, non di attribuire il problema di latenza alla versione.

Su una copia Git che contiene quei commit, `git switch main` torna al ramo corrente. Se serve aggiornare il ramo dal remoto: `git fetch origin` seguito da `git pull --ff-only origin main`, dopo aver controllato `git status --short`. Un ramo creato in PowerShell con `git switch -c prima-dei-cinque-preset 4109cad` resta locale finché non viene pubblicato; un `git pull` sul rover non trasferisce automaticamente quel ramo. Non sovrascrivere modifiche locali non salvate quando si cambia ramo.
