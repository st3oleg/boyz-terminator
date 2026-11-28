# Fase 2 — Hub Ubuntu in sola lettura

Questa procedura descrive il collaudo iniziale con dispositivi simulati. Per il Rover reale e il pulsante di avvio, usa la [guida operativa dell'HP](../../HP-linux/docs/registrare-rover.md#avvio-su-richiesta).

L'hub riceve eventi, li conserva in PostgreSQL e mostra l'ultimo stato ricevuto di Rover e Base RTK. I primi due dispositivi sono simulati. La pagina si aggiorna ogni 5 secondi e, dopo 30 secondi senza nuovi eventi, mostra offline. L'ora di ricezione viene assegnata dal database. Il server rimane attivo anche quando chiudi il browser.

## Avvio sull'HP

Serve Docker Engine aggiornato (almeno 28) con il plugin Compose. Se manca, segui la [guida ufficiale per Ubuntu](https://docs.docker.com/engine/install/ubuntu/). Usa `sudo docker compose` se l'utente richiede privilegi per Docker.

Copia il pacchetto della fase 2 sull'HP, estrailo in una nuova cartella e apri il terminale nella sottocartella `hub`. In alternativa usa la sottocartella `hub` del repository.

```bash
umask 077
python3 setup_demo.py
sudo systemctl enable --now docker
sudo docker compose up -d --build --wait
curl --fail http://127.0.0.1:8090/healthz
python3 demo.py
```

Apri [la dashboard sull'HP](http://127.0.0.1:8090) subito dopo il collaudo. Dovresti vedere due schede simulate. Dopo circa 30 secondi dalla ricezione degli ultimi eventi appariranno offline. Esegui di nuovo `python3 demo.py` per una nuova coppia di eventi.

Il file `.env` contiene le password del database e i token dei dispositivi. `setup_demo.py` lo crea con permessi `600` su Ubuntu e conserva un file già presente. Tienine una copia protetta insieme al backup. Conserva i dati PostgreSQL nel volume Compose `pgdata`, preservato da `docker compose down`; `down -v` rimuoverebbe quel volume.

## Accesso da Windows

Il servizio web ascolta su `127.0.0.1:8090` sull'HP. PostgreSQL è accessibile solo nella rete interna di Compose. Per aprire la dashboard da Windows, controlla prima eventuali configurazioni Serve esistenti. Se la radice HTTPS è libera, pubblica la dashboard nella tailnet e apri da Windows l'indirizzo HTTPS che Tailscale restituisce. Se Serve richiede di abilitare HTTPS, segui la richiesta mostrata dal terminale. [Guida Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)

```bash
tailscale serve status
sudo tailscale serve --bg http://127.0.0.1:8090
```

Chi può raggiungere l'endpoint HTTPS nella tailnet può leggere la dashboard e l'API dispositivi. Limita quell'accesso con le regole della tailnet prima di caricare dati reali. Per inviare eventi serve il token del singolo dispositivo.

## Verifica backup e ripristino

Esegui la prova dopo `python3 demo.py` e senza altri invii durante il confronto. Da `hub` salva il dump in un percorso protetto e ripristinalo in un database separato nello stesso container. Sostituisci il percorso del dump con una cartella su un secondo supporto se vuoi conservare il backup. [PostgreSQL pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html) · [PostgreSQL pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html)

```bash
umask 077
dump="hub-$(date +%Y%m%d-%H%M%S).dump"
restore_db="hub_restore_$(date +%s)"
sudo docker compose exec -T db pg_dump -U hub -Fc hub > "$dump" &&
sudo docker compose exec -T db createdb -U hub "$restore_db" &&
sudo docker compose exec -T db pg_restore -U hub --exit-on-error -d "$restore_db" < "$dump"
```

Se il ripristino riesce, il comando seguente deve mostrare lo stesso conteggio (almeno 2 dopo la demo) e lo stesso digest in entrambe le righe.

```bash
query="SELECT count(*), md5(string_agg(to_jsonb(e)::text, '' ORDER BY device_id, boot_id, sequence)) FROM hub_events e"
sudo docker compose exec -T db psql -U hub -d hub -At -v ON_ERROR_STOP=1 -c "$query"
sudo docker compose exec -T db psql -U hub -d "$restore_db" -At -v ON_ERROR_STOP=1 -c "$query"
```

## Interfaccia e limiti

| Metodo e percorso | Risultato |
| --- | --- |
| `GET /` | Dashboard separata dalla guida. |
| `GET /healthz` | HTTP 200 se l'applicazione riesce a leggere la tabella PostgreSQL. |
| `GET /api/v1/devices` | Dispositivi configurati, ultimo evento ricevuto e stato calcolato in base all'età. |
| `POST /api/v1/events` | JSON fino a 64 KiB, conforme al [contratto v1](../schemas/hub-event-v1.schema.json). Il token Bearer è associato a identità e tipo. HTTP 201 dopo il commit, 200 per un retry identico, 409 per stessa chiave con contenuto diverso. |

Nella fase iniziale la convalida copre il formato comune dell'evento. I campi interni di `payload` restano aperti in attesa di campioni live. L'interfaccia mostra una sintesi dell'ultimo evento. Gli eventi precedenti restano in PostgreSQL. Le decisioni su frequenza, conservazione e viste storiche dipendono dalle misure della fase 1. L'invio dai dispositivi reali con coda locale è previsto nella fase 3.
