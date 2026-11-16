# Analisi e verifica GPS RTK

**Aggiornato:** 16 novembre 2026  
**Scopo:** ripetere la verifica della catena Base → RTCM → Rover → ricevitore GNSS prima di sviluppare o provare la guida Pure Pursuit.

## Configurazione osservata

| Elemento | Base | Rover |
|---|---|---|
| Host Raspberry Pi | `antenna` | `terminator` |
| Hardware | Raspberry Pi 4 Model B Rev 1.5 + Waveshare LC29H-BS | Raspberry Pi 4 Model B Rev 1.5 + Waveshare LC29H-DA |
| Collegamento HAT | Innestato sul GPIO del Pi | Innestato sul GPIO del Pi |
| Porta seriale osservata | `/dev/serial0` → `/dev/ttyS0` | `/dev/serial0` → `/dev/ttyS0` |
| Servizio principale osservato | `base.service` | test manuale `test_rtk_serial_link.py` |

La documentazione Waveshare indica che il jumper UART va impostato nella posizione prevista per Raspberry Pi (B nella guida Waveshare). La posizione fisica del jumper e il corretto contatto/innesto non sono stati verificati a distanza: controllarli visivamente a robot spento. Non collegare contemporaneamente più programmi alla seriale GNSS.

## Che cosa è stato verificato

1. **Base attiva:** `base.service` risultava `active (running)` ed eseguiva `/home/antenna/Documents/base_manager.py` da `/home/antenna/Documents`.
2. **RTCM generato dalla Base:** il log riportava messaggi 1005; il server esponeva RTCM TCP sulla porta 5000 e API HTTP sulla 8080.
3. **Rete:** il tentativo verso l'indirizzo LAN `192.168.1.13:5000` dal Rover era andato in timeout. La connessione all'indirizzo Tailscale della Base sulla porta 5000 riusciva. Ricavare sempre l'indirizzo Tailscale corrente, perché può cambiare.
4. **Trasporto e integrità RTCM:** in una cattura di 10 secondi il Rover ha ricevuto 5204 byte, con 10 messaggi 1005 e 9 ciascuno dei tipi 1074, 1084, 1094, 1114 e 1124; CRC errati: 0.
5. **Ricevitore Rover:** il test seriale ha mostrato porta aperta, RTCM connesso, byte scritti in aumento e correzioni fresche. La soluzione è passata da DGPS a FLOAT e poi a FIX, con 38 satelliti segnalati. Nei log inviati il FIX è rimasto presente per il campione mostrato; l'età correzioni era circa 0,1–0,7 s e non erano riportati errori.

Queste prove dimostrano la ricezione di correzioni RTCM valide e un RTK FIX riportato dal ricevitore durante il test. **Non dimostrano ancora accuratezza su un punto noto, stabilità prolungata/in movimento o sicurezza per la guida autonoma.**

## Nota importante su NTRIP

La configurazione osservata non usa un client/server NTRIP: `base_manager.py` inoltra frame RTCM grezzi su una connessione TCP privata tramite Tailscale (`porta 5000`). NTRIP è un protocollo distinto (tipicamente HTTP con mountpoint/autenticazione). In questa configurazione, verificare “NTRIP” non è corretto: si devono verificare Base RTCM, trasporto TCP, scrittura seriale e stato GNSS del Rover.

## Procedura ripetibile

Eseguire i comandi sul Pi indicato. Non incollare il prompt (`antenna@...$`) insieme al comando.

### 1. Identità e seriale, su entrambi i Pi

```bash
cat /proc/device-tree/model; echo
uname -a
ls -l /dev/serial*
readlink -f /dev/serial0
```

Risultato atteso per la configurazione già osservata: Raspberry Pi 4 Model B Rev 1.5 e `/dev/serial0` risolto in `/dev/ttyS0`.

### 2. Stato Base e log RTCM

Sul Pi `antenna`:

```bash
sudo systemctl status base.service --no-pager
sudo systemctl show base.service -p ExecStart -p WorkingDirectory
sudo journalctl -u base.service --since "5 minutes ago" --no-pager | grep -E '\[RTCM\]|\[SERIALE\]|RTCM 100[56]'
sudo ss -lntp | grep -E ':5000|:8080'
```

Il log `Posizione da RTCM 1005` prova che la Base decodifica il riferimento della stazione, ma da solo non prova che i messaggi di osservazione arrivino al Rover. Il server dovrebbe ascoltare su TCP 5000 e HTTP 8080.

### 3. Connettività Base → Rover

Sul Pi Base trovare l'indirizzo Tailscale corrente:

```bash
tailscale ip -4
```

Sul Rover sostituire `<IP_TAILSCALE_BASE>` con quel valore:

```bash
nc -vz -w 3 <IP_TAILSCALE_BASE> 5000
```

Atteso: `succeeded`. Se si usa la LAN, verificare prima che i due Pi siano sulla stessa rete e usare l'IP LAN attuale della Base. Un test TCP riuscito verifica solo la porta, non i byte RTCM.

### 4. Osservare i byte RTCM dal Rover

Questo controllo riceve alcuni secondi di flusso TCP. Interrompere dopo circa 10 secondi con `Ctrl+C`; il conteggio byte deve essere maggiore di zero. Il test dettagliato CRC/message-type già eseguito ha dato 5204 byte, messaggi 1005/1074/1084/1094/1114/1124 e zero errori CRC.

```bash
python3 -c 'import socket,time; s=socket.create_connection(("<IP_TAILSCALE_BASE>",5000),3); s.settimeout(1); end=time.monotonic()+10; n=0
while time.monotonic()<end:
 try: d=s.recv(4096)
 except socket.timeout: continue
 if not d: break
 n+=len(d)
print("byte RTCM ricevuti:",n); s.close()'
```

Per ripetere la verifica CRC e il conteggio per tipo RTCM, usare lo script/one-liner Python con parser CRC-24Q eseguito nel test originale; il risultato di riferimento è riportato sopra. Un `nc` riuscito o byte non nulli non sostituiscono la verifica del CRC.

### 5. Test seriale GNSS/RTCM sul Rover

Prima accertarsi che nessun altro processo stia usando la porta. Avviare il test manuale già predisposto dall'utente:

```bash
sudo fuser -v /dev/ttyS0
python3 /home/terminator/Documents/tests/test_rtk_serial_link.py
```

Tenere il Rover fermo, antenna con cielo libero e test in esecuzione. Lasciare osservare per almeno alcuni minuti o fino a FIX stabile, poi terminare con `Ctrl+C`. Le colonne da controllare sono:

- `seriale=OK`;
- `RTCM=connesso` e `byte_scritti` in aumento;
- `eta_correzione` bassa e aggiornata;
- `GNSS=FLOAT` durante la convergenza, poi `GNSS=FIX` persistente;
- `errore=—`.

Se la porta è occupata, individuare il processo prima di terminare servizi. Non eseguire il server completo del rover solo per questo controllo se non è necessario: può inizializzare altri sottosistemi, inclusi i motori.

## Interpretazione rapida

| Evidenza | Che cosa dimostra | Che cosa non dimostra |
|---|---|---|
| Base logga RTCM 1005/1006 | Presenza del riferimento Base | Osservazioni RTCM ricevute dal Rover |
| Porta 5000 raggiungibile | Percorso TCP aperto | Dati RTCM validi |
| Byte e CRC validi, tipi MSM presenti | Flusso di correzioni integro fino al client | Che il ricevitore le abbia applicate |
| `byte_scritti` sale e correzioni fresche | I byte vengono inoltrati alla seriale Rover | Accuratezza assoluta della posizione |
| `GNSS=FIX` stabile | Il ricevitore dichiara RTK fixed | Accuratezza verificata o comportamento affidabile in movimento |

## Verifiche ancora necessarie prima di usare Pure Pursuit sul veicolo

- Provare la posizione Rover su un punto di coordinate note e misurare errore e ripetibilità.
- Registrare una sessione più lunga, includendo eventuale perdita/ripristino rete e passaggio FIX/FLOAT.
- Ripetere con Rover in movimento e verificare frequenza, timestamp, qualità, latitudine/longitudine e salti di posizione.
- Confermare montaggio e orientamento delle antenne, cielo libero, cavi e jumper UART; per il FIX usare le condizioni raccomandate dal produttore.
- Per il controllore Pure Pursuit, considerare valido il fix solo con qualità FIX e dati recenti; passare a arresto controllato quando FIX o correzioni diventano obsoleti. Validare prima con motori disabilitati/robot sollevato e un arresto indipendente.

## Riferimenti hardware

- [Waveshare LC29H GPS HAT](https://www.waveshare.com/lc29h-gps-hat.htm)
- [Waveshare Wiki: LC29H(X) GPS/RTK HAT](https://www.waveshare.com/wiki/LC29H%28XX%29_GPS/RTK_HAT)
- [Quectel LC29H RTK Application Note](https://quectel.com/content/uploads/2024/02/Quectel_LC29HBACADA_DRRTK_Application_Note_V1.0.pdf)
- [Quectel LC29H Hardware Design](https://quectel.com/content/uploads/2024/02/Quectel_LC29H_Series_Hardware_Design_V1.0.pdf)

