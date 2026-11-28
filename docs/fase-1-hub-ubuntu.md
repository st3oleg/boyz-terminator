# Fase 1 — misure e contratto dati dell'hub Ubuntu

**Avviata il 24 novembre 2026.** Questa fase documenta ciò che si può misurare dal codice e dalle missioni locali. Le misure di rete e di latenza del Rover fisico restano da acquisire. L'operatore ha fornito l'indirizzo Tailscale del Rover e ha collegato il PC Ubuntu a Tailscale. L'architettura obiettivo è in [Hub Ubuntu](hub-ubuntu.md).

## Inventario verificato nel codice locale

| Flusso | Stato e frequenza attuali | File |
| --- | --- | --- |
| Comando manuale | La pagina apre `/ws` sullo stesso host. `motor_step` e `stop` ricevono `command_ack` con tempo di elaborazione del server. Il browser mostra RTT e stima di andata. Il watchdog motori scade dopo 1 s; la pagina invia heartbeat ogni 800 ms. | `static/autopilota.html`, `telemetry_server.py` |
| Telemetria per browser | Il server prepara un payload ogni 0,2 s, circa 5 Hz, quando ci sono client WebSocket. Il valore PING della pagina è l'età del messaggio e dipende anche dalla sincronizzazione degli orologi. | `telemetry_server.py`, `static/autopilota.html` |
| Missione GNSS | Durante la registrazione viene salvato un punto per nuovo GGA, tipicamente circa 1 Hz, con qualità RTK, IMU, motori e diagnostica. Il JSON viene scritto alla conclusione della registrazione. | `telemetry_server.py`, `missions/` |
| Stato Rover verso Base | `rover_uplink_task` invia uno stato HTTP circa ogni 1 s se `BASE_API_URL` o `BASE_TAILSCALE_HOST` è configurato. Gli errori sono registrati ma il payload non entra in una coda durevole. | `telemetry_server.py` |
| RTCM Base → Rover | Il client Rover si collega direttamente alla Base sulla porta configurata, predefinita `5000`; il server Base locale espone RTCM/TCP su quella porta. | `modules/rtcm_client.py`, `../boyz-antenna-main/base_manager.py` |
| Archivio Base locale | La versione locale Base conserva ultima posizione e stato Rover in SQLite; non è un archivio multi-dispositivo verificato in campo. | `../boyz-antenna-main/base_manager.py` |

I numeri descrivono il checkout locale e non dimostrano che la stessa versione sia installata sui Raspberry. La prova da terminale di una tratta Pure Pursuit resta separata dalla teleoperazione web.

Nelle [note video e rete](video-telemetria-e-rete.md#significato-dei-numeri-di-latenza) l'operatore aveva riferito PING della telemetria di circa 500–700 ms e poi fino a 1200 ms. Sono osservazioni storiche non replicate, non misure del tempo di risposta dei comandi.

## Verifica live della Base, 24 novembre 2026

Dal PC Windows dell'operatore la Base risultava online in Tailscale, mentre il Rover risultava offline. Cinque `tailscale ping` verso la Base hanno usato un percorso diretto sulla LAN e hanno riportato **5–9 ms**. Dieci richieste di sola lettura a `GET /api/state` hanno risposto tutte con HTTP 200: **mediana 21 ms**, **p95 125,5 ms**, minimo 13,6 ms e massimo 125,5 ms. La prima richiesta isolata, eseguita prima della serie, aveva impiegato 881,2 ms e non è inclusa nei dieci campioni; l'avvio della connessione può incidere. Queste misure descrivono solo il percorso PC→Base in quel momento, senza carico controllato. Non misurano la latenza della teleoperazione PC→Rover.

La risposta Base conteneva `type`, `timestamp`, `base` e `rover`. Il blocco `base` conteneva `lat`, `lon`, `alt`, `source`, `quality`, `updated_at`, `available` e `age_seconds`. Il blocco `rover` conteneva anche `last_seen`, `online`, `fix_timestamp`, `fix_age_seconds` e `rtcm`. Sono stati letti solo i nomi dei campi, senza riportare coordinate o altri valori. La struttura osservata è coerente con il codice locale della Base, ma non identifica la versione esatta installata.

## Verifica live del PC Ubuntu, 24–27 novembre 2026

Il PC Ubuntu `stefano-hp-notebook` è stato aggiunto alla tailnet con indirizzo `100.125.71.48`. Un output del terminale condiviso dall'operatore identificava Ubuntu 22.04.5 LTS con GNOME su Wayland. Il 24 novembre il PC ha risposto a `tailscale ping` in 8 ms e, in una verifica successiva, in 5 ms; il percorso indicato era diretto sulla LAN. La porta RDP `3389` accettava connessioni, mentre SSH `22` e RDP `3390` non rispondevano. Queste prove confermavano connettività in quel momento, La disponibilità dell'hub non era stata verificata in quelle prove di rete.

Dopo un riavvio forzato del PC Ubuntu, il 25 novembre `tailscale status` lo indicava online, ma tre tentativi di `tailscale ping` sono scaduti. Il Rover `100.73.187.83` risultava offline e non ha risposto agli stessi tentativi. La raggiungibilità di Ubuntu va quindi ricontrollata dal PC stesso prima di misurare il percorso Ubuntu→Rover. La fase 1 si può proseguire dal terminale locale Ubuntu o dalla chat sul PC Linux: RDP e `mstsc` non sono prerequisiti.

Il 26 novembre, dal PC Windows, tre nuovi `tailscale ping` verso Ubuntu e Rover sono ancora scaduti. `tailscale status` indicava Ubuntu online e Rover offline. Una connessione TCP verso `100.125.71.48:3389` è però riuscita, mentre le porte `22` e `3390` non rispondevano. Ubuntu era quindi raggiungibile almeno via TCP sull'indirizzo Tailscale: il timeout di `tailscale ping` da solo non dimostra che sia spento.

In un resoconto ricevuto il 27 novembre, l'operatore ha riportato dal terminale Ubuntu `systemctl is-active tailscaled` → `active`, `tailscale ip -4` → `100.125.71.48` e tre timeout con `no reply` da `tailscale ping --c=3 100.73.187.83`. L'operatore ha confermato che il Rover era spento. Nello stesso giorno, `tailscale status` dal PC Windows indicava Ubuntu online e Rover offline. Il test Ubuntu→Rover è stato quindi eseguito, ma non può fornire latenza o percorso `direct`/`relay` finché il Rover resta spento.

## Volume osservato nei file disponibili

Le sette missioni recenti in formato 3, esclusa la storica `Fix_1.json`, contengono complessivamente **441 punti** e occupano **461.957 byte** come JSON leggibile, includendo metadati ed eventi. Il punto tipico serializzato senza spazi occupa circa **646–654 byte**, secondo la missione. I campioni coprono intervalli di circa 1 s. La missione storica `Fix_1.json` ha uno schema più piccolo e non è rappresentativa del formato attuale.

Come sola stima di dimensionamento, 650 byte per punto a 1 Hz continuo equivalgono a circa **56 MB/giorno per Rover** di payload grezzo; a 5 Hz sarebbero circa **281 MB/giorno**. Il registratore attuale non acquisisce missioni per l'intera giornata. Queste cifre non includono indici del database, eventi, ritrasmissioni o video e non misurano la dimensione del payload WebSocket. Servono misure reali prima di fissare capacità del disco e durata della conservazione.

## Misure ancora da acquisire sul Rover

Eseguire le prove con la versione del software e il tipo di rete annotati. La misura dei comandi richiede l'operatore al Rover, motori disabilitati fisicamente o veicolo messo in sicurezza, nessun altro client che cambi `dry_run`, e l'uso del solo comando **STOP** dalla pagina Autopilota. Lo STOP invia un `command_ack` ma non richiede movimento. Non usare uno script che invii comandi di trazione per misurare la latenza.

1. Annotare data/ora, browser, rete dell'operatore, rete Rover, indirizzo usato e versione Git installata sul Rover.
2. Dal dispositivo dell'operatore eseguire `tailscale ping <HOST_TAILSCALE_ROVER>` e annotare se il collegamento finale è `direct` oppure `relay`, con tempi osservati. Ripetere quando il PC Ubuntu sarà nella tailnet.
3. Aprire la pagina `http://<HOST_TAILSCALE_ROVER>:8080/autopilota.html`. Con le condizioni sopra rispettate, inviare almeno 20 comandi **STOP** separati e annotare per ciascuno l'RTT mostrato in **INPUT → ROVER**, il tempo `rover` e gli eventuali `TIMEOUT`. Calcolare mediana, percentile 95 e massimo. Il valore di andata è una stima che presume una rete simmetrica, non la misura del movimento fisico.
4. Nello stesso intervallo annotare PING della telemetria e RTT della pagina camera come metriche distinte. Non usare il PING della telemetria come RTT del comando. Annotare camera attiva e stato dello stream video.
5. Ripetere la misura con le due configurazioni di rete che interessano davvero l'uso: per esempio LAN e hotspot. Quando l'hub esisterà, confrontare la guida diretta con la dashboard Ubuntu aperta e il caricamento dati attivo.
6. Per il volume di rete, registrare per 5 minuti numero e dimensione dei frame WebSocket `telemetry` con gli strumenti di rete del browser; misurare separatamente gli upload delle missioni. Non includere il video nel valore della telemetria.

Tabella per il resoconto di ciascuna prova:

| Data e rete | Versione Rover | Tailscale direct/relay | Comandi e timeout | RTT comando mediana/p95/max (ms) | RTT camera (ms) | PING telemetria (ms) | Note video |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| Da misurare | Da rilevare | Da rilevare | Da misurare | Da misurare | Da misurare | Da misurare | Da rilevare |

## Contratto dati proposto

Il formato seguente è **una proposta per la fase 2**, non un payload già prodotto dal Rover. Il vincolo strutturale è nel file [hub-event-v1.schema.json](../schemas/hub-event-v1.schema.json). Ogni messaggio inviato all'API Ubuntu contiene:

| Campo | Regola |
| --- | --- |
| `schema_version` | Intero, inizialmente `1`; una modifica incompatibile richiede una nuova versione. |
| `device_id` | Identità stabile assegnata al dispositivo, distinta dal nome visualizzato e dall'indirizzo IP. |
| `device_type` | `rover`, `base` o un nuovo tipo registrato; non dedurlo dal payload. |
| `boot_id` | UUID nuovo a ogni avvio del servizio che produce i messaggi. |
| `sequence` | Intero crescente dentro il singolo `boot_id`; la chiave `(device_id, boot_id, sequence)` deduplica i retry e mostra eventuali lacune. |
| `event_type` | Tipo versionato, inizialmente `status`, `telemetry`, `diagnostic_event` o `mission_index`. |
| `observed_at` | Ora UTC della misura, oppure `null` se l'orologio non è attendibile; non sostituire una misura mancante con l'ora di ricezione. |
| `monotonic_ms` | Tempo monotono del dispositivo da quell'avvio; permette l'ordine locale anche se l'orologio UTC cambia. |
| `payload` | Oggetto specifico del tipo, con unità esplicite. Coordinate assenti sono `null`, non `(0, 0)`. |

L'API assegna `received_at` in UTC e non accetta questo campo dal client. La dashboard calcola online/offline dall'età di `received_at`; mostra separatamente la freschezza del fix GNSS e delle correzioni RTCM. Una conferma API significa che l'evento è stato persistito. Il dispositivo può eliminare l'evento dalla sua coda locale solo dopo tale conferma. I comandi manuali non transitano in questa API; il Rover invia successivamente i relativi eventi diagnostici.

### Mappatura dai payload attuali

| Sorgente attuale | Trasformazione richiesta |
| --- | --- |
| `telemetry_server.py` WebSocket: `gps` e `rover` | Sono due viste della stessa posizione. Creare un solo evento Rover, senza duplicare la misura. Conservare qualità RTK e timestamp del fix separati dall'ora del messaggio. |
| `telemetry_server.py` POST alla Base | Riutilizzare i campi GNSS/IMU/RTCM già raccolti, aggiungendo identità, `boot_id`, `sequence` e coda durevole prima di cambiare destinazione. L'invio attuale non ha questi campi né retry persistente. |
| `base_manager.py` `GET /api/state` | Il risultato contiene stato della Base **e** ultima copia dello stato Rover. Attribuire alla Base solo le sue misure; la copia Rover non è una seconda misura del Rover. |
| Timestamp attuali | `fix_timestamp` è in secondi Unix, mentre `telemetry.timestamp` del WebSocket è in millisecondi Unix. Convertire esplicitamente a UTC e non confondere i due campi. |
| Coordinate assenti | Il Rover usa talvolta `(0, 0)` come valore iniziale. Nell'hub convertirlo in `null` con qualità assente, senza rappresentarlo come posizione geografica. |

Esempio **sintetico** di messaggio senza posizione valida:

```json
{
  "schema_version": 1,
  "device_id": "rover-001",
  "device_type": "rover",
  "boot_id": "d602bb32-8ab3-4d1d-8210-c6e1fd9e8189",
  "sequence": 17,
  "event_type": "status",
  "observed_at": null,
  "monotonic_ms": 123456,
  "payload": {
    "gnss": {"rtk_status": "NO FIX", "lat": null, "lon": null},
    "rtcm": {"connected": false, "age_seconds": null}
  }
}
```

Prima dell'implementazione, confrontare questo contratto con almeno un payload reale di Rover e Base. Definire poi limiti numerici, dimensioni massime, autenticazione del dispositivo, unità e politica di conservazione in base alle misure. Non copiare token o credenziali nei messaggi, nella pagina o nei log.

## Stato della fase

- **Completato:** inventario dei flussi, lettura dei JSON recenti, stima iniziale del volume, schema proposto e verifica live della struttura e raggiungibilità dell'API Base.
- **Non misurato:** latenza reale dei comandi al Rover, tipo di collegamento Tailscale verso il Rover, dimensione dei frame live, volume su una sessione lunga e confronto con Ubuntu acceso. Da questa sessione sia SSH sia una richiesta di sola lettura a `/camera/ping` sul Rover sono andati in timeout; il Rover risultava offline in Tailscale. Ubuntu è nella tailnet, `tailscaled` risulta attivo e il tentativo Ubuntu→Rover è scaduto mentre il Rover era spento. Ripetere la prova con il Rover acceso.
- **Criterio di chiusura:** tabella delle misure reali compilata per almeno due condizioni di rete, contratto confrontato con payload reali di Rover e Base, frequenza di acquisizione e conservazione iniziali definite. Solo allora dimensionare disco e iniziare l'API della fase 2.
