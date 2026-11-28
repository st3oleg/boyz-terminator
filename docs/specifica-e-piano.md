# Specifica obiettivo e piano di sviluppo

**Nota stato al 24 novembre 2026:** il repository include trasporto RTCM Base→Rover via TCP (non NTRIP), geometria Pure Pursuit, simulazione Webots su `Fix_1`, registrazione GNSS circa 1 Hz, trim persistente e un controllore sperimentale da terminale che collega Pure Pursuit al driver motori per una tratta in avanti supervisionata. Le nuove misure a 30% e 50% alimentano un profilo PWM iniziale. Un avvio sul Raspberry si è arrestato prima della trazione; il completamento della corsa in campo e la sicurezza dell'uso autonomo non sono dimostrati. Vedere [Architettura RTK](architettura-rtk-base-rover.md), [Riproduzione traccia](riproduzione-traccia.md) e [Calibrazione motori e tracce](calibrazione-motori-e-tracce.md).

## Obiettivo di prodotto

Robot terrestre elettrico a guida automatica RTK per lo sfalcio controllato di erba nei campi e tra filari. La macchina deve poter percorrere una zona autorizzata, mantenere una copertura di taglio misurabile, arrestare trazione e attrezzo in caso di anomalia e consentire all'operatore di riprendere il controllo in sicurezza.

Non fissare ancora valori di velocità, massa, superficie giornaliera, pendenza o autonomia: vanno derivati dall'uso agricolo previsto, dalla macchina e dalla valutazione dei rischi. Il limite di 5 km/h e gli altri numeri nello storico sono ipotesi, non requisiti validati né esenzioni normative.

## Architettura proposta

### 1. Controllore di missione

Calcola traiettorie, sequenza dei filari, manovre di testa, sovrapposizione del piatto, stato missione e ritorno/recupero. Deve lavorare su coordinate metriche locali e su una mappa con confini, ostacoli fissi e zone vietate. La pagina web è supervisione: una perdita della UI non deve lasciare il robot in moto.

#### Geofencing e modalità manuale/autonoma

- L'operatore deve poter disegnare più perimetri autorizzati sulla mappa, modificarne i vertici, rimuoverli e ritrovarli al successivo accesso. La UI conserva i poligoni nel `localStorage` del browser; la pagina Riproduzione può anche salvare un GeoJSON sul Rover. Il controllore sperimentale legge un file geofence locale con nome fissato nel codice. Questi passaggi non formano ancora una configurazione autorizzata e sincronizzata.
- Il requisito funzionale richiesto è: il robot può eseguire missioni autonome solo dentro un perimetro autorizzato. Fuori dai perimetri può muoversi solo in modalità manuale, con supervisione dell'operatore. Nessuna missione autonoma deve partire se i confini mancano, non sono validi o non sono disponibili al controllore a bordo.
- La verifica deve avvenire nel controllore a bordo a ogni aggiornamento di posizione e prima di ogni comando autonomo, non soltanto nel browser. Il controllore sperimentale verifica FIX, freschezza e distanza dal geofence locale, ma la validazione fisica del margine resta aperta. La modalità manuale può superare il confine solo tramite comando esplicito; l'interfaccia deve mostrare chiaramente modalità e stato del confine.
- Definire una fascia di rispetto basata su errore e integrità GNSS, dimensioni/ingombro del robot e distanza/tempo di arresto. Se la posizione o il fix non sono affidabili, la missione autonoma deve essere sospesa e il robot deve attuare lo stato sicuro deciso dall'analisi dei rischi. I perimetri software non sostituiscono recinzioni o protezioni fisiche.
- Specificare se servono anche zone interne vietate, gestione dei fori nei poligoni, import/export, versionamento, firma/configurazione autorizzata e comportamento in caso di modifica mentre una missione è attiva.

### 2. Localizzazione e percezione

- GNSS RTK con qualità, timestamp, età delle correzioni, integrità e diagnostica; blocco della guida automatica se la soluzione non soddisfa i limiti definiti.
- IMU calibrata e encoder ruota per heading/odometria e rilevamento di slittamento o incongruenza.
- Percezione ostacoli indipendente e adeguata al campo (es. combinazione di sensori), con copertura e tempi di arresto verificati in condizioni avverse.
- Sensori di inclinazione/assetto, velocità e stato di alimentazione; diagnostica dei sensori e del controller.

### 3. Controllo del veicolo e dell'attrezzo

Anello chiuso con feedback encoder, velocità controllata, accelerazione limitata, sterzata e frenatura coerenti con l'inerzia. Attrezzo di taglio con interblocco dedicato, protezioni fisiche, rilevazione di sovraccarico e arresto sicuro. Guasto software o perdita di alimentazione di controllo deve condurre a uno stato sicuro definito dall'analisi dei rischi.

### 4. Catena di sicurezza indipendente

Pulsante di arresto fisico accessibile, stop remoto con feedback, abilitazione manuale intenzionale, watchdog hardware, controllo dei contattori/driver, rilevamento di apertura protezioni e uscite sicure per trazione e lama. La funzione di sicurezza non deve dipendere da WebSocket, Raspberry Pi, rete cellulare o pagina browser. Definire il livello di prestazione richiesto mediante valutazione dei rischi e verifica specialistica.

### 5. Comunicazioni e software

WebSocket autenticato e cifrato, comandi con autorizzazione, numero di sequenza e scadenza, un solo controllore attivo con lease, registri immutabili degli eventi e aggiornamenti controllati. Separare rete macchina, rete supervisione e servizi video. Il comportamento in assenza di rete dev'essere locale e sicuro.

#### Correzioni GNSS RTCM/NTRIP

RTCM è il formato dei messaggi di correzione GNSS; NTRIP è un protocollo di trasporto in streaming su rete. Per ottenere RTK, una Base GNSS configurata come riferimento deve generare le correzioni e inoltrarle al ricevitore Rover. Implementare un servizio sul dispositivo Base e un client/bridge sul Rover che consegni i byte RTCM alla porta d'ingresso prevista dal ricevitore; il flusso di correzioni deve restare separato dal WebSocket della dashboard. In alternativa, se la Base usa una radio dedicata, il trasporto radio deve consegnare lo stesso flusso al Rover.

Il sistema deve esporre alla telemetria almeno stato di connessione, età dell'ultima correzione, dati ricevuti e stato RTK. La modalità autonoma deve rifiutare o interrompere la missione quando le correzioni scadono o il fix non soddisfa i limiti definiti. Nel checkout locale sono presenti client RTCM/TCP e scrittura seriale coordinata sul Rover; l'inoltro TCP privato è stato provato manualmente e il ricevitore ha raggiunto FIX nel test. Non è un client NTRIP e l'integrazione completa Base/Rover resta da installare e verificare. Vedere [Analisi GPS RTK](gap_analisi_risoluzione_GPSRTK.md).

## Requisiti da definire prima del progetto dettagliato

1. Coltura/appezzamento: filare o campo aperto, larghezza interfilare, lunghezza fila, ostacoli, pendenza e condizioni stagionali.
2. Operazione: manutenzione frequente o primo taglio, altezza obiettivo, larghezza e tipo di apparato, gestione dei residui.
3. Prestazioni: ha/giorno, qualità/capacità di copertura, precisione di traiettoria richiesta rispetto al piatto, autonomia e tempi di fermo.
4. Limiti operativi: velocità, pendenza, pioggia/fango, persone/animali ammessi nell'area, recinzioni e confini; semantica e margine dei perimetri autorizzati e comportamento al passaggio tra manuale e autonomia.
5. Veicolo: massa, dimensioni, baricentro, ruote, trazione, freni, energia, BMS, ricarica, protezione IP e gestione termica.
6. Conformità: mercato e modalità di fornitura, destinazione d'uso, valutazione dei rischi, standard applicabili, fascicolo tecnico e processo di validazione.

## Stati operativi suggeriti

`SPENTO → AUTOTEST → PRONTO → MANUALE oppure MISSIONE_SUPERVISIONATA → PAUSA/ARRESTO → RECUPERO → SPENTO`

Ogni transizione deve richiedere condizioni esplicite. La missione autonoma può partire solo con sensori validi, perimetro autorizzato caricato e verificato, attrezzo protetto, operatore autorizzato e presenza dell'operatore nella zona di supervisione definita. Fuori da tutti i perimetri autorizzati è ammessa solo la modalità manuale; l'uscita dal perimetro durante l'autonomia deve attivare lo stato sicuro previsto. Per perdita RTK, correzioni RTCM scadute, ostacolo, inclinazione eccessiva, errore attuatore, batteria fuori soglia, sensore non aggiornato o anomalia termica, il robot deve interrompere la missione ed entrare nello stato sicuro previsto. Il “ritorno a casa” non va considerato più sicuro dello stop se la localizzazione o il percorso sono degradati.

## Piano a fasi con criteri di uscita

| Fase | Lavoro | Criterio per proseguire |
|---|---|---|
| 0 — Definizione | Specificare appezzamento, tipo di taglio, prestazioni attese e analisi preliminare dei rischi. Inventariare hardware reale e risolvere le discrepanze dello storico. | Requisiti misurabili e BOM/cablaggio verificati. |
| 1 — Hardening teleoperazione | Autenticazione/TLS, accesso singolo, logging, watchdog dei sensori, stop fisico indipendente, protezione video e limiti motore. | Prove di perdita rete/processo/alimentazione dimostrano lo stato sicuro su banco. |
| 2 — Navigazione senza attrezzo | Calibrare GNSS/IMU/encoder; acquisire perimetri autorizzati e trasferirli al controllore a bordo; percorrere linee e svolte in area chiusa a velocità ridotta. | Prove con confine, margine e perdita RTK dimostrano che l'autonomia non oltrepassa l'area autorizzata; modalità manuale verificata separatamente. |
| 3 — Validazione ostacoli | Testare persone/manichini, oggetti bassi, pali, vegetazione, luce, polvere, pioggia simulata e terreno inclinato, con arresti misurati. | Requisiti protettivi e limiti d'uso documentati e verificati. |
| 4 — Taglio in ambiente controllato | Attrezzo protetto, area segregata, supervisione ravvicinata; misurare qualità, capacità, energia e manutenzione contro baseline manuale. | Criteri agronomici, operativi ed economici raggiunti senza eventi di sicurezza. |
| 5 — Pilota sorvegliato | Estendere progressivamente superfici/condizioni; registrare ogni intervento e fermata; aggiornare fascicolo di rischio. | Evidenza sufficiente per la modalità d'impiego prevista e valutazione di conformità completata prima della messa in servizio commerciale. |

## Metriche di accettazione da concordare

Specificare limiti quantitativi per: errore laterale massimo/percentile, tempo e distanza d'arresto, fascia di confine, tasso di rilevazione ostacoli, frequenza di falsi arresti, area non coperta, altezza residua, capacità ettari/ora, kWh/ha, disponibilità operativa, interventi umani per ora e costo totale per ettaro. Non è responsabile inventare soglie senza dimensioni, velocità, massa, lama e contesto d'uso.

## Priorità immediate

1. Congelare le caratteristiche della macchina reale e scegliere il primo caso d'uso ristretto.
2. Non collegare la lama durante le prove software e non usare il prototipo per lavoro autonomo.
3. Chiudere prima le vulnerabilità di rete e progettare la catena fisica di arresto.
4. Rendere i dati GNSS validi e freschi una condizione verificata, non un semplice indicatore grafico.
5. Costruire navigazione senza taglio e misurare ripetibilità; dopo, integrare e validare l'attrezzo.
6. Coinvolgere un esperto di sicurezza macchine agricole per il risk assessment e il percorso di conformità.

