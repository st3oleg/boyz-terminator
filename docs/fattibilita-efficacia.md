# Studio di efficacia e fattibilità

## Valutazione sintetica

Un robot RTK può essere utile per mantenere erba e infestanti basse con passaggi frequenti, specialmente tra filari accessibili e con vegetazione non troppo alta. La tecnologia è plausibile; l'efficacia del robot di questo repository resta **non dimostrata**. È presente un controllore sperimentale per una tratta in avanti supervisionata, ma non una macchina automatica di taglio né una missione completa validata in campo.

**Giudizio per impiego:**

- **Promettente:** sfalcio di mantenimento a bassa altezza, su area piccola/medio-piccola, terreno conosciuto, accesso controllato, copertura GNSS buona e possibilità di supervisionare.
- **Da dimostrare:** filari stretti, pendenze, terreno irregolare, erba densa o alta, residui, frutti caduti, fango, alberi che schermano il GNSS, lavoro vicino a persone/animali.
- **Non supportato allo stato attuale:** lavoro autonomo non sorvegliato, copertura completa garantita, ritorno automatico, evitamento sicuro degli ostacoli, arresto sicuro della lama o conformità per l'immissione sul mercato.

## Cosa suggerisce la ricerca disponibile

Uno studio in un piccolo pereto giapponese ha osservato un robot rasaerba commerciale con area nominale di circa 3.200 m², larghezza di taglio 24 cm e lavoro distribuito su 24 ore includendo la ricarica. Il robot manteneva una cotica più bassa con funzionamento frequente, ma la sua efficienza di taglio per singolo passaggio era inferiore a quella di alcune macchine convenzionali; il tempo operativo prolungato compensava in parte questo limite. Gli autori hanno rilevato impatti ripetuti contro gli alberi e arresti/impuntamenti dovuti ai frutti caduti; la convenienza economica risultava per il piccolo appezzamento studiato, ma non per superfici di 0,66–1 ha con quella macchina. [Studio sul pereto](https://www.mdpi.com/2077-0472/11/2/113)

Questo studio sostiene il caso d'uso “tagliare spesso e poco” in un frutteto piccolo, non dimostra che un rover artigianale pesante, con lama diversa, RTK e terreno italiano ottenga gli stessi risultati. In particolare, il taglio di erba alta/biomassa densa richiede potenza, gestione del carico, controllo termico e un attrezzo adatto; un robot leggero progettato per manutenzione continua non equivale a una trinciatrice agricola.

Una valutazione recente di un robot elettrico agricolo riporta risultati promettenti in prove reali, ma l'efficienza dipende da carico, velocità, attrezzo e coltura. È un richiamo a misurare la macchina e l'operazione specifiche, non un benchmark direttamente trasferibile a questo progetto. [Studio su robot agricolo elettrico](https://www.sciencedirect.com/science/article/pii/S2772375524002004)

## Fattori che determinano il risultato

1. **Tipo di sfalcio:** mantenimento frequente oppure primo taglio di erba alta. Il primo è molto più favorevole al piccolo robot.
2. **Larghezza utile e velocità reale:** determinano la capacità teorica; sterzate, ostacoli, ricarica, sovrapposizione e ripassi la riducono.
3. **Qualità del taglio:** altezza uniforme, residui, strappi, intasamento e ricrescita. La precisione RTK da sola non migliora il taglio.
4. **Campo:** geometria dei filari, pendenza, buche, fango, erba bagnata e copertura del cielo condizionano trazione, localizzazione e arresto.
5. **Energia e manutenzione:** energia per ettaro, autonomia utile, tempi di ricarica, pulizia del piatto, lame, ruote e interventi per impuntamenti.
6. **Sicurezza di persone e fauna:** un apparato rotante può proiettare pietre e detriti. La sola precisione di posizione non rileva persone, animali o ostacoli bassi.

## Metodo per quantificare l'efficacia sul prototipo

Definire prima il campo di prova e confrontare il robot con la pratica locale, nello stesso appezzamento e in condizioni comparabili. Registrare almeno:

- superficie realmente coperta per ora **di calendario** e per ora di lavoro attivo;
- percentuale di area non tagliata e sovrapposizione/ripassi tramite mappa di copertura;
- altezza dell'erba e biomassa residua in punti campionati prima/dopo;
- kWh/ha e tempo di ricarica, fermate non pianificate e minuti di intervento umano;
- tagli/urti, impuntamenti, errori GNSS, perdita RTK, deviazione dai confini e arresti;
- costo totale annuale confrontato con la macchina convenzionale, includendo acquisto, usura, energia, manutenzione, supervisione e certificazione.

Ripetere per diverse altezze/densità dell'erba, pendenza, copertura GNSS e condizioni del suolo. Conservare video/log sincronizzati e criteri misurabili di successo definiti prima delle prove. Il primo ciclo deve essere svolto senza lama attiva; la fase con attrezzo richiede una valutazione dei rischi approvata e supervisione.

Capacità teorica di taglio per una macchina con larghezza utile `w` (m) e velocità `v` (m/s): `w × v × 3,6` ha/h prima delle perdite. Il valore operativo va moltiplicato per il fattore di efficienza osservato, includendo svolte, sovrapposizioni, ricarica e soste. Senza larghezza, velocità, autonomia e dati di campo del prototipo non è possibile dare una stima numerica affidabile.

## Fattibilità tecnica

RTK è appropriato per seguire linee ripetibili quando base/correzioni e geometria GNSS funzionano bene. Non è sufficiente come unico sensore di navigazione o sicurezza: può degradarsi sotto chiome o accanto a ostacoli. Il registratore conserva qualità ed età del fix e accetta anche soluzioni non FIX recenti; il controllore sperimentale richiede FIX e correzioni fresche. Servono ancora localizzazione complementare, encoder, heading validato e una risposta di arresto verificata sul veicolo.

Il telaio, il peso, la potenza e la larghezza di taglio non sono specificati in modo verificabile nel repository. Lo storico elenca componenti diversi e non allineati al codice. Di conseguenza non è ancora possibile dimensionare capacità, batteria, freni, stabilità, produttività o costo.

## Rischi di efficacia

- Un percorso RTK preciso può comunque tagliare male se il piatto si intasa o la velocità supera la capacità di taglio.
- Un errore sistematico della base o una traccia acquisita durante un fix degradato trasferisce un errore ripetibile al percorso.
- Navigare vicino ai tronchi affidandosi solo a RTK rischia collisioni e danni a piante e robot.
- Un veicolo con poca massa può perdere trazione; uno più pesante aumenta compattamento e conseguenze degli urti.
- L'operatore che deve recuperare spesso il robot può annullare il risparmio di manodopera.

## Quadro normativo e standard

Il riferimento europeo per le macchine è il Regolamento (UE) 2023/1230, che si applicherà dal **20 gennaio 2027**. Includere fin dall'inizio la valutazione dei rischi, i requisiti essenziali, la documentazione tecnica e la procedura di conformità pertinenti al prodotto concreto; la sola velocità inferiore a una soglia non esenta automaticamente da tali obblighi. [Testo consolidato EUR-Lex](https://eur-lex.europa.eu/eli/reg/2023/1230/en)

La serie **ISO 18497:2024** riguarda macchine agricole parzialmente automatizzate, semi-autonome e autonome. Le parti includono principi di progettazione, protezione dagli ostacoli, zone operative e metodi di verifica. La parte 2 sottolinea che nessuna tecnologia di percezione funziona perfettamente in ogni condizione e richiede di considerare mancata/tardiva rilevazione, occlusione, pioggia/polvere, luce, vibrazione e ostacoli negativi. È quindi necessario un progetto di protezione validato per il campo d'impiego specifico. [ISO 18497-1:2024](https://committee.iso.org/cms/live/live/en/sites/isoorg/contents/data/standard/08/26/82684.html?browse=tc), [ISO 18497-2:2024](https://cdn.standards.iteh.ai/samples/82686/a057c4df64db436fb462ea4bb21d60c6/ISO-18497-2-2024.pdf)

Il testo normativo e gli standard vanno verificati con un professionista di sicurezza macchine e con l'organismo/consulente competente per la categoria finale, inclusi gli eventuali standard di prodotto e obblighi nazionali. Questa sezione è un orientamento tecnico, non un parere legale né una dichiarazione di conformità.

