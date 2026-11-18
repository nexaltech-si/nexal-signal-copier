//+------------------------------------------------------------------+
//|                                          NexalSignalMirrorEA.mq5   |
//|   NEXAL — trade-copier EA for OTHER accounts      |
//+------------------------------------------------------------------+
//
//  ⚠ THIS EA PLACES, MODIFIES AND CLOSES REAL ORDERS. Read this header.
//
//  WHAT THIS EA DOES (v2 — full copier)
//  -------------------------------------
//  Every InpPollSeconds it reads a live snapshot of your MASTER MT5 account
//  (GET /api/ea/mirror — every open position and pending order, straight from
//  the broker) and reconciles THIS account against it, so this account does
//  exactly what the master does:
//
//    master opens a position / places a pending  -> open / place it here
//    master moves SL or TP (breakeven, trailing) -> same SL/TP here
//    master moves a pending order's price        -> same price here
//    master partially closes                     -> close the same SHARE here
//    master closes a position                    -> close it here
//    master cancels a pending order              -> cancel it here
//
//  That covers trades opened or managed by hand on the master terminal too,
//  not only the bot's own (InpCopyManual). Lot sizes are THIS account's own
//  (InpSizingMode) — partial closes are copied as a proportion, so 50% off
//  the master is 50% off here whatever the lot sizes.
//
//  Upgrading from v1 (which only opened trades and left exits to SL/TP):
//  positions v1 opened are adopted automatically and managed from then on.
//
//  WHY IT NEVER CLOSES ON A GLITCH
//  --------------------------------
//  "Ticket missing from the snapshot" means "master closed it", so a broken
//  snapshot must never look empty:
//   - The server refuses (HTTP 503) any snapshot it cannot vouch for — bridge
//     error, terminal disconnected, or "no positions" while the master still
//     shows margin/floating P/L. On any non-200 this EA does NOTHING.
//   - The feed must parse completely: version header, row counts that match
//     the header, and the 'E' terminator. Anything else is ignored.
//   - A ticket must be missing from InpCloseConfirmPolls CONSECUTIVE good
//     snapshots before this EA closes or cancels anything.
//   - If the master ACCOUNT changes (different login), it stops acting until
//     you confirm with InpAcceptMasterChange=true.
//
//  WHAT IT DOES NOT CHASE
//  -----------------------
//  A master position older than InpMaxTradeAgeMin is not opened here at
//  market (the price has moved on). Positions that were already open when the
//  backend last restarted have an unknown age and are likewise not chased.
//  Pending orders are always copied — they sit at a fixed price.
//  If this account's own copy closes by itself (its own SL/TP hit, or you
//  close it by hand) it is NOT reopened.
//
//  STATE
//  -----
//  Each copy carries "ASM:<master ticket>" in its comment, and the master ->
//  mirror ticket links (with the lot sizes they started at, for proportional
//  partial closes) are kept in MQL5\Files\NexalMirror_<login>_<magic>.csv, so a
//  restart picks up exactly where it left off. HEDGING accounts only.
//
//  STATUS REPORTING
//  ----------------
//  Every InpReportSeconds (and right after it acts) it POSTs its account,
//  links and recent actions to /api/ea/report — that is what the dashboard's
//  Trade Copier page shows: which accounts are connected, what is in sync,
//  what was skipped and why.
//
//  SETUP
//  -----
//  1. Tools -> Options -> Expert Advisors -> "Allow WebRequest for listed URL":
//     add your dashboard's public URL.
//  2. InpApiUrl = that URL; InpApiKey = a key from the dashboard's API Keys page.
//  3. Leave InpDryRun=true first: it logs (and the dashboard shows) what it
//     WOULD do. Set InpDryRun=false once you're satisfied.
//  4. Attach to ANY one chart — it copies every symbol, not just the chart's.
//
//  WebRequest() does not run in the Strategy Tester. Validate on a demo.
//
//+------------------------------------------------------------------+
#property copyright "NEXAL"
#property version   "2.00"
#property description "Copies the NEXAL master account's live positions & orders onto this account — opens, SL/TP changes, partial closes, closes and cancels. Places real orders."

#include <Trade\Trade.mqh>

#define EA_VERSION     "2.00"
//--- Must match EA_MIRROR_VERSION / ROW_FIELDS in src/api/ea_mirror_router.py.
#define FEED_VERSION   4
#define ROW_FIELDS     14
#define MAX_ROWS       300
#define TAG_PREFIX     "ASM:"   // v2: ASM:<master ticket>
#define LEGACY_TAG     "ASF:"   // v1: ASF:<short trade id>
#define LOG_ROWS       10
#define MAX_EVENTS     100

//--- Link states (master ticket -> this account's copy)
#define LS_OPEN     0   // copy is an open position
#define LS_PENDING  1   // copy is a pending order
#define LS_SKIPPED  2   // decided not to copy (stale, unsupported...) — not persisted
#define LS_DONE     3   // copy closed on its own here — never reopen
#define LS_DRY      4   // dry run: would have copied — not persisted

enum ENUM_COPY_SIZING
  {
   SIZE_RISK_PERCENT   = 0, // Risk % of this balance (from master SL)
   SIZE_EQUITY_RATIO   = 1, // Master lots x (this equity / master equity)
   SIZE_LOT_MULTIPLIER = 2, // Master lots x multiplier (1.0 = same lots)
   SIZE_FIXED_LOT      = 3  // Fixed lot
  };

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group "═══ Connection ═══"
input string   InpApiUrl            = "https://dashboard.example.com"; // Dashboard base URL (must be whitelisted)
input string   InpApiKey            = "";        // X-EA-Key (your key from the API Keys page)
input int      InpPollSeconds       = 5;         // Snapshot poll interval (seconds)
input int      InpReportSeconds     = 15;        // Status report to dashboard (seconds, 0=off)
input int      InpTimeoutMs         = 5000;      // HTTP timeout (ms)

input group "═══ What to copy ═══"
input bool     InpDryRun            = true;      // TRUE = log only, place/modify/close NOTHING
input bool     InpCopyOpens         = true;      // Copy new master positions
input bool     InpCopyPending       = false;     // Hold nothing while master is pending (wait for RUNNING position)
input bool     InpCopySLTP          = true;      // Follow master SL/TP changes (tighten-only SL)
input bool     InpCopyPartials      = true;      // Follow master partial closes (proportionally)
input bool     InpCopyCloses        = true;      // Close here when the master closes
input bool     InpCopyManual        = true;      // Also copy trades opened by hand on the master
input int      InpCloseConfirmPolls = 2;         // Snapshots a ticket must be gone before closing here
input int      InpMaxTradeAgeMin    = 0;         // Max master age for market open (min, 0=off; falls back to limit)
input int      InpMaxEntryDeviationPts = 0;      // Hard point cap on adverse entry drift (points, 0=off)
input double   InpMinRemainingRR    = 0.8;       // Opportunity Check: min remaining R:R required to enter (0=off)
input double   InpSlippageRiskTolerance = 0.15;  // Anti-slippage tolerance in R (default 0.15R -> limit fallback)
input double   InpSpreadMultiplier  = 0.0;       // Dynamic spread buffer on SL (multiplier * spread, 0=off)
input bool     InpAcceptMasterChange = false;    // Accept a different master account login

input group "═══ Execution ═══"
input long     InpMagic             = 20260101;  // Magic number for this EA's trades (same as v1)
input int      InpMaxSlippage       = 20;        // Max slippage (points)
input double   InpMaxSpreadPoints   = 30.0;      // Max spread for market opens (points, 0=off)

input group "═══ Sizing & risk ═══"
input ENUM_COPY_SIZING InpSizingMode = SIZE_RISK_PERCENT; // Lot sizing
input double   InpRiskPercent       = 1.0;       // Risk % per signal (risk mode)
input double   InpLotMultiplier     = 1.0;       // Multiplier (equity-ratio / multiplier modes)
input double   InpFixedLot          = 0.01;      // Lot per signal (fixed mode)
input double   InpMaxLot            = 5.0;       // Hard lot ceiling per position
input double   InpMaxRiskOvershoot  = 1.5;       // Risk mode: refuse if real risk > this x target
input int      InpMaxPositions      = 10;        // Max concurrent copied positions (0=off)
input double   InpMaxDailyLossPct   = 5.0;       // Stop NEW copies after this daily loss % (0=off)

input group "═══ Filter ═══"
input string   InpAllowedSymbols    = "";        // CSV whitelist (master names), empty = all

input group "═══ Symbol mapping ═══"
input string   InpSymbolSuffix      = "";        // This broker's suffix, e.g. ".r" or "m"
input string   InpSymbolPrefix      = "";        // This broker's prefix
input bool     InpAutoDetectSuffix  = true;      // Auto-detect suffix at startup
input string   InpSymbolMap         = "";        // Explicit map, e.g. "GOLD=XAUUSD.x;US30Cash=DJ30"

input group "═══ On-chart panel ═══"
input bool     InpShowPanel         = true;      // Show status panel on chart
input int      InpPanelX            = 10;        // Distance from right edge (px)
input int      InpPanelY            = 20;        // Distance from top (px)
input int      InpPanelFontSize     = 8;         // Font size
input color    InpPanelColor        = clrGainsboro; // Default text colour

//+------------------------------------------------------------------+
//| Types                                                            |
//+------------------------------------------------------------------+
struct MasterRow
  {
   bool     isOrder;
   string   ticket;
   string   symbol;       // master symbol with broker affixes stripped
   string   side;         // BUY / SELL, or BUY_LIMIT / SELL_STOP / ... for orders
   double   volume;
   double   price;        // position open price / order price
   double   sl;
   double   tp;
   double   age;          // minutes since fill/placement; < 0 = unknown
   long     magic;
   string   tradeId;      // "-" for trades not placed by the bot
   string   signalId;
   string   rawSymbol;    // exact master symbol name
   string   channel;
   double   riskFraction; // this row's share of its signal's risk budget
   double   initSl;       // initial stop loss at placement/entry
  };

struct Link
  {
   string   master;       // master ticket
   ulong    mirror;       // this account's position/order ticket (0 = none)
   int      state;        // LS_*
   double   masterVol0;   // master volume when linked — base for partial-close ratio
   double   mirrorVol0;   // our volume when linked
   int      misses;       // consecutive good snapshots without this master ticket
   bool     inSync;
   string   note;
   string   symbol;       // our symbol
   string   side;
  };

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
CTrade     trade;

MasterRow  g_rows[];
int        g_rowCount = 0;
Link       g_links[];

string     g_masterLogin   = "";
double     g_masterBalance = 0.0;
double     g_masterEquity  = 0.0;
string     g_pinnedMaster  = "";
bool       g_masterMismatch = false;

string     g_stateFile = "";
bool       g_dirty     = false;

ulong      g_lastPollMs   = 0;
ulong      g_lastReportMs = 0;
int        g_pollFailures = 0;
bool       g_feedOk       = false;
string     g_lastError    = "";

double     g_dayStartEquity = 0.0;
int        g_dayStamp       = -1;
bool       g_halted         = false;

string     g_detectedSuffix = "";
string     g_detectedPrefix = "";

//--- Transient "can't copy this right now" reasons, keyed by master ticket —
//--- re-evaluated every poll, logged only when the reason changes.
string     g_waitKeys[];
string     g_waitNotes[];

//--- Actions since the last successful report.
string     g_evType[], g_evSymbol[], g_evMaster[], g_evMirror[], g_evMsg[];
int        g_evCount = 0;

string     g_logLines[LOG_ROWS];
color      g_logColors[LOG_ROWS];
int        g_logCount = 0;

int        g_synced = 0;
int        g_issues = 0;

//+------------------------------------------------------------------+
//| Logging / events                                                 |
//+------------------------------------------------------------------+
void Log(const string msg)     { Print("[ASM] ", msg); }
void LogWarn(const string msg) { Print("[ASM][WARN] ", msg); }
void LogErr(const string msg)  { Print("[ASM][ERROR] ", msg); }

void PanelLog(const string text, const color clr)
  {
   if(g_logCount < LOG_ROWS)
     {
      g_logLines[g_logCount]  = text;
      g_logColors[g_logCount] = clr;
      g_logCount++;
      return;
     }
   for(int i = 1; i < LOG_ROWS; i++)
     {
      g_logLines[i - 1]  = g_logLines[i];
      g_logColors[i - 1] = g_logColors[i];
     }
   g_logLines[LOG_ROWS - 1]  = text;
   g_logColors[LOG_ROWS - 1] = clr;
  }

color EventColor(const string type)
  {
   if(type == "OPEN" || type == "FILL")  return(clrLime);
   if(type == "PLACE" || type == "MODIFY") return(clrDeepSkyBlue);
   if(type == "CLOSE" || type == "PARTIAL" || type == "CANCEL") return(clrOrange);
   if(type == "ERROR") return(clrOrangeRed);
   if(type == "DRY" || type == "WARN") return(clrGold);
   return(clrGray);
  }

//--- Record an action: terminal log, chart panel, and the next dashboard report.
void AddEvent(const string type, const string symbol, const string master,
              const ulong mirror, const string msg)
  {
   string line = type + " " + symbol + (master != "" ? " #" + master : "") + " — " + msg;
   if(type == "ERROR")
      LogErr(line);
   else if(type == "WARN")
      LogWarn(line);
   else
      Log(line);
   PanelLog(type + " " + symbol + " " + msg, EventColor(type));

   if(g_evCount == MAX_EVENTS)
     {
      for(int i = 1; i < MAX_EVENTS; i++)
        {
         g_evType[i - 1] = g_evType[i];     g_evSymbol[i - 1] = g_evSymbol[i];
         g_evMaster[i - 1] = g_evMaster[i]; g_evMirror[i - 1] = g_evMirror[i];
         g_evMsg[i - 1] = g_evMsg[i];
        }
      g_evCount--;
     }
   g_evType[g_evCount]   = type;
   g_evSymbol[g_evCount] = symbol;
   g_evMaster[g_evCount] = master;
   g_evMirror[g_evCount] = (mirror > 0 ? StringFormat("%I64u", mirror) : "");
   g_evMsg[g_evCount]    = msg;
   g_evCount++;
  }

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpApiKey == "")
     {
      LogErr("InpApiKey is empty — the feed requires X-EA-Key. EA halted.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpPollSeconds < 2)
     {
      LogErr("InpPollSeconds must be >= 2 (WebRequest blocks the EA while it waits).");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpReportSeconds != 0 && InpReportSeconds < 5)
     {
      LogErr("InpReportSeconds must be 0 (off) or >= 5.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpCloseConfirmPolls < 1)
     {
      LogErr("InpCloseConfirmPolls must be >= 1.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpSizingMode == SIZE_RISK_PERCENT && InpRiskPercent <= 0.0)
     {
      LogErr("InpRiskPercent must be > 0 in risk sizing mode.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if((InpSizingMode == SIZE_EQUITY_RATIO || InpSizingMode == SIZE_LOT_MULTIPLIER) && InpLotMultiplier <= 0.0)
     {
      LogErr("InpLotMultiplier must be > 0.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpMaxRiskOvershoot < 1.0)
     {
      LogErr("InpMaxRiskOvershoot must be >= 1.0 (it is a multiple of the risk target).");
      return(INIT_PARAMETERS_INCORRECT);
     }
   //--- Netting accounts merge every trade on a symbol into one position, so
   //--- per-ticket copying (and proportional partial closes) can't work there.
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      LogErr("This account is not a HEDGING account. The copier needs one position per ticket — EA halted.");
      return(INIT_FAILED);
     }

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippage);
   trade.SetAsyncMode(false);

   ArrayResize(g_evType, MAX_EVENTS);   ArrayResize(g_evSymbol, MAX_EVENTS);
   ArrayResize(g_evMaster, MAX_EVENTS); ArrayResize(g_evMirror, MAX_EVENTS);
   ArrayResize(g_evMsg, MAX_EVENTS);

   if(InpAutoDetectSuffix)
      DetectSymbolAffixes();

   g_stateFile = StringFormat("NexalMirror_%I64d_%I64d.csv", AccountInfoInteger(ACCOUNT_LOGIN), InpMagic);
   LoadState();
   ResetDailyEquityBaseline();

   EventSetTimer(InpPollSeconds);

   Log("─────────────────────────────────────────────");
   Log("NEXAL Trade Copier EA v" + EA_VERSION + " started");
   Log("  URL     : " + InpApiUrl + "/api/ea/mirror");
   Log("  Magic   : " + IntegerToString(InpMagic));
   Log("  Mode    : " + (InpDryRun ? "DRY RUN (nothing will be placed, modified or closed)" : "LIVE TRADING"));
   Log("  Sizing  : " + SizingLabel());
   Log("  Copying : opens=" + (string)InpCopyOpens + " pending=" + (string)InpCopyPending +
       " sltp=" + (string)InpCopySLTP + " partials=" + (string)InpCopyPartials +
       " closes=" + (string)InpCopyCloses + " manual=" + (string)InpCopyManual);
   Log("  State   : " + g_stateFile + " (" + IntegerToString(ArraySize(g_links)) + " link(s) restored)");
   Log("  Suffix  : '" + EffectiveSuffix() + "'  Prefix: '" + EffectivePrefix() + "'");
   if(InpDryRun)
      LogWarn("DRY RUN is ON — set InpDryRun=false only once you've reviewed the log / dashboard.");
   Log("─────────────────────────────────────────────");

   UpdatePanel();
   PollAndReconcile();
   MaybeReport(true);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   SaveState();
   RemovePanel();
   Log("EA stopped (reason=" + IntegerToString(reason) + "). Copied positions are NOT closed.");
  }

void OnTimer()
  {
   CheckDailyLossLimit();
   PollAndReconcile();
   MaybeReport(false);
   UpdatePanel();
  }

string SizingLabel()
  {
   switch(InpSizingMode)
     {
      case SIZE_RISK_PERCENT:   return(StringFormat("RISK %.2f%%", InpRiskPercent));
      case SIZE_EQUITY_RATIO:   return(StringFormat("EQUITY RATIO x%.2f", InpLotMultiplier));
      case SIZE_LOT_MULTIPLIER: return(StringFormat("LOTS x%.2f", InpLotMultiplier));
      default:                  return(StringFormat("FIXED %.2f", InpFixedLot));
     }
  }

//+------------------------------------------------------------------+
//| Poll the snapshot and reconcile this account against it          |
//+------------------------------------------------------------------+
void PollAndReconcile()
  {
   string body = "";
   if(!FetchSnapshot(body))
     {
      g_feedOk = false;
      return; // no information — hold everything as is
     }
   if(!ParseSnapshot(body))
     {
      g_feedOk = false;
      g_pollFailures++;
      return;
     }
   g_feedOk     = true;
   g_lastPollMs = GetTickCount64();
   if(g_pollFailures > 0)
     {
      Log("Snapshot recovered after " + IntegerToString(g_pollFailures) + " failed poll(s).");
      g_pollFailures = 0;
     }
   g_lastError = "";

   //--- Pin the master account: a different login means every ticket differs,
   //--- which would otherwise read as "master closed everything".
   if(g_pinnedMaster == "")
     {
      g_pinnedMaster = g_masterLogin;
      g_dirty = true;
     }
   else if(g_pinnedMaster != g_masterLogin)
     {
      if(!InpAcceptMasterChange)
        {
         g_lastError = "Master account changed from " + g_pinnedMaster + " to " + g_masterLogin +
                       " — holding. Set InpAcceptMasterChange=true to copy the new master (copies of the old one will then be closed).";
         if(!g_masterMismatch)
            LogErr(g_lastError);
         g_masterMismatch = true;
         return;
        }
      AddEvent("WARN", "", "", 0, "Master account changed " + g_pinnedMaster + " -> " + g_masterLogin + "; now copying the new master.");
      g_pinnedMaster = g_masterLogin;
      g_dirty = true;
     }
   g_masterMismatch = false;

   RefreshLinks();
   AdoptUntracked();

   // Priority Exit Ordering (Spec Section 5):
   // Process exits (CLOSE / CANCEL for vanished tickets) FIRST to free margin & concurrency slots
   ProcessMissing();

   // Process active links: partial closes & tighten-only SL/TP sync
   for(int i = 0; i < g_rowCount; i++)
     {
      int idx = FindLinkByMaster(g_rows[i].ticket);
      if(idx >= 0)
         ProcessRow(i);
     }

   // Compute risk fractions across active signals
   ComputeRiskFractions();

   // Process new entries / resting limits for unlinked master positions
   for(int i = 0; i < g_rowCount; i++)
     {
      int idx = FindLinkByMaster(g_rows[i].ticket);
      if(idx < 0)
         ProcessRow(i);
     }

   PruneWaits();
   ComputeSyncStats();
   SaveState();
  }

//+------------------------------------------------------------------+
//| HTTP                                                             |
//+------------------------------------------------------------------+
string JsonField(const string body, const string key)
  {
   string pat = "\"" + key + "\":\"";
   int p1 = StringFind(body, pat);
   if(p1 < 0)
      return("");
   p1 += StringLen(pat);
   int p2 = StringFind(body, "\"", p1);
   return(p2 > p1 ? StringSubstr(body, p1, p2 - p1) : "");
  }

bool FetchSnapshot(string &body)
  {
   string url = InpApiUrl + "/api/ea/mirror";
   string headers = "X-EA-Key: " + InpApiKey + "\r\n";
   char   post[], result[];
   string resultHeaders;

   ResetLastError();
   int status = WebRequest("GET", url, headers, InpTimeoutMs, post, result, resultHeaders);
   if(status == -1)
     {
      int err = GetLastError();
      g_pollFailures++;
      g_lastError = (err == 4014)
                    ? "WebRequest not allowed — add " + InpApiUrl + " under Tools -> Options -> Expert Advisors."
                    : "WebRequest failed, error " + IntegerToString(err);
      if(g_pollFailures == 1 || g_pollFailures % 20 == 0)
         LogErr(g_lastError + " (failure #" + IntegerToString(g_pollFailures) + ")");
      return(false);
     }

   string text = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(status == 200)
     {
      body = text;
      return(true);
     }

   g_pollFailures++;
   string detail = JsonField(text, "detail");
   if(detail == "")
      detail = JsonField(text, "error");
   if(status == 403)
      g_lastError = "403 Forbidden" + (detail != "" ? " — " + detail : "") + ". Check InpApiKey.";
   else if(status == 503)
      g_lastError = "Master snapshot unavailable (503) — holding, no actions" + (detail != "" ? ": " + detail : "");
   else
      g_lastError = "HTTP " + IntegerToString(status) + " from snapshot" + (detail != "" ? ": " + detail : "");
   if(g_pollFailures == 1 || g_pollFailures % 20 == 0)
      LogErr(g_lastError + " (failure #" + IntegerToString(g_pollFailures) + ")");
   return(false);
  }

//+------------------------------------------------------------------+
//| Parse. False = unsafe to act on (any doubt -> do nothing).       |
//+------------------------------------------------------------------+
double FieldToDouble(const string v)
  {
   if(v == "-" || v == "")
      return(0.0);
   return(StringToDouble(v));
  }

bool ParseSnapshot(const string body)
  {
   string lines[];
   int n = StringSplit(body, '\n', lines);
   bool sawHeader = false, sawEnd = false;
   int expectPos = -1, expectOrd = -1, gotPos = 0, gotOrd = 0;
   g_rowCount = 0;
   ArrayResize(g_rows, MAX_ROWS);

   for(int i = 0; i < n; i++)
     {
      string line = lines[i];
      StringTrimLeft(line);
      StringTrimRight(line);
      if(line == "")
         continue;
      if(line == "E")
        {
         sawEnd = true;
         continue;
        }

      string f[];
      int fc = StringSplit(line, '|', f);
      if(fc <= 0)
         continue;

      if(f[0] == "V")
        {
         if(fc < 8)
           {
            g_lastError = "Malformed snapshot header.";
            LogErr(g_lastError);
            return(false);
           }
         int ver = (int)StringToInteger(f[1]);
         if(ver != FEED_VERSION)
           {
            g_lastError = "Snapshot version " + IntegerToString(ver) + " but this EA expects " +
                          IntegerToString(FEED_VERSION) + " — update the EA. Holding.";
            LogErr(g_lastError);
            return(false);
           }
         g_masterLogin   = f[3];
         g_masterBalance = FieldToDouble(f[4]);
         g_masterEquity  = FieldToDouble(f[5]);
         expectPos       = (int)StringToInteger(f[6]);
         expectOrd       = (int)StringToInteger(f[7]);
         sawHeader = true;
         continue;
        }

      if(f[0] == "P" || f[0] == "O")
        {
         if(fc < ROW_FIELDS)
           {
            g_lastError = "Snapshot row with " + IntegerToString(fc) + " fields (expected " +
                          IntegerToString(ROW_FIELDS) + ") — holding.";
            LogErr(g_lastError);
            return(false);
           }
         if(g_rowCount >= MAX_ROWS)
           {
            g_lastError = "Snapshot exceeds MAX_ROWS (" + IntegerToString(MAX_ROWS) + ") — holding.";
            LogErr(g_lastError);
            return(false);
           }
         FillRow(f, g_rows[g_rowCount]);
         if(g_rows[g_rowCount].isOrder) gotOrd++; else gotPos++;
         g_rowCount++;
        }
     }

   //--- A truncated or partial body must never read as "fewer positions".
   if(!sawHeader || !sawEnd || gotPos != expectPos || gotOrd != expectOrd)
     {
      g_lastError = StringFormat("Incomplete snapshot (header=%s end=%s positions %d/%d orders %d/%d) — holding.",
                                 (string)sawHeader, (string)sawEnd, gotPos, expectPos, gotOrd, expectOrd);
      LogErr(g_lastError);
      return(false);
     }
   ArrayResize(g_rows, g_rowCount);
   return(true);
  }

void FillRow(const string &f[], MasterRow &r)
  {
   r.isOrder      = (f[0] == "O");
   r.ticket       = f[1];
   r.symbol       = f[2];
   r.side         = f[3];
   r.volume       = FieldToDouble(f[4]);
   r.price        = FieldToDouble(f[5]);
   r.sl           = FieldToDouble(f[6]);
   r.tp           = FieldToDouble(f[7]);
   r.age          = (f[8] == "-" ? -1.0 : FieldToDouble(f[8]));
   r.magic        = StringToInteger(f[9]);
   r.tradeId      = f[10];
   r.signalId     = f[11];
   r.rawSymbol    = f[12];
   r.channel      = f[13];
   r.riskFraction = 1.0;
   int fc = ArraySize(f);
   r.initSl       = (fc >= 15 && f[14] != "" && f[14] != "-") ? FieldToDouble(f[14]) : r.sl;
   if(r.initSl <= 0.0)
      r.initSl    = r.sl;
  }

int FindRow(const string ticket)
  {
   for(int i = 0; i < g_rowCount; i++)
      if(g_rows[i].ticket == ticket)
         return(i);
   return(-1);
  }

//+------------------------------------------------------------------+
//| Links                                                            |
//+------------------------------------------------------------------+
int FindLinkByMaster(const string master)
  {
   for(int i = ArraySize(g_links) - 1; i >= 0; i--)
      if(g_links[i].master == master)
         return(i);
   return(-1);
  }

int FindLinkByMirror(const ulong mirror)
  {
   if(mirror == 0)
      return(-1);
   for(int i = ArraySize(g_links) - 1; i >= 0; i--)
      if(g_links[i].mirror == mirror)
         return(i);
   return(-1);
  }

int AddLink(const string master, const ulong mirror, const int state, const double masterVol0,
            const double mirrorVol0, const string symbol, const string side, const string note)
  {
   int n = ArraySize(g_links);
   ArrayResize(g_links, n + 1);
   g_links[n].master     = master;
   g_links[n].mirror     = mirror;
   g_links[n].state      = state;
   g_links[n].masterVol0 = masterVol0;
   g_links[n].mirrorVol0 = mirrorVol0;
   g_links[n].misses     = 0;
   g_links[n].inSync     = (state == LS_OPEN || state == LS_PENDING);
   g_links[n].note       = note;
   g_links[n].symbol     = symbol;
   g_links[n].side       = side;
   ClearWait(master);
   g_dirty = true;
   return(n);
  }

void RemoveLink(const int i)
  {
   int n = ArraySize(g_links);
   if(i < n - 1)
      g_links[i] = g_links[n - 1];
   ArrayResize(g_links, n - 1);
   g_dirty = true;
  }

string StateName(const int s)
  {
   switch(s)
     {
      case LS_OPEN:    return("OPEN");
      case LS_PENDING: return("PENDING");
      case LS_SKIPPED: return("SKIPPED");
      case LS_DONE:    return("DONE");
      default:         return("DRY");
     }
  }

//--- Set a link's note, logging it only when it changes (no per-poll spam).
void SetLinkNote(const int i, const string note, const bool isError)
  {
   if(g_links[i].note == note)
      return;
   g_links[i].note = note;
   if(note != "")
      AddEvent(isError ? "ERROR" : "WARN", g_links[i].symbol, g_links[i].master, g_links[i].mirror, note);
  }

//+------------------------------------------------------------------+
//| Transient wait reasons (no link yet)                             |
//+------------------------------------------------------------------+
void SetWait(const string master, const string symbol, const string note)
  {
   for(int i = ArraySize(g_waitKeys) - 1; i >= 0; i--)
     {
      if(g_waitKeys[i] != master)
         continue;
      if(g_waitNotes[i] != note)
        {
         g_waitNotes[i] = note;
         AddEvent("SKIP", symbol, master, 0, "not copied yet: " + note);
        }
      return;
     }
   int n = ArraySize(g_waitKeys);
   ArrayResize(g_waitKeys, n + 1);
   ArrayResize(g_waitNotes, n + 1);
   g_waitKeys[n]  = master;
   g_waitNotes[n] = note;
   AddEvent("SKIP", symbol, master, 0, "not copied yet: " + note);
  }

void ClearWait(const string master)
  {
   for(int i = ArraySize(g_waitKeys) - 1; i >= 0; i--)
     {
      if(g_waitKeys[i] != master)
         continue;
      int n = ArraySize(g_waitKeys);
      g_waitKeys[i]  = g_waitKeys[n - 1];
      g_waitNotes[i] = g_waitNotes[n - 1];
      ArrayResize(g_waitKeys, n - 1);
      ArrayResize(g_waitNotes, n - 1);
      return;
     }
  }

void PruneWaits()
  {
   for(int i = ArraySize(g_waitKeys) - 1; i >= 0; i--)
      if(FindRow(g_waitKeys[i]) < 0)
         ClearWait(g_waitKeys[i]);
  }

//+------------------------------------------------------------------+
//| Persistence: MQL5\Files\NexalMirror_<login>_<magic>.csv           |
//|   M|<pinned master login>                                        |
//|   L|master|mirror|state|masterVol0|mirrorVol0|symbol|side         |
//| SKIPPED and DRY links are re-derivable and not saved; DONE is     |
//| saved so a copy that closed on its own is never reopened.         |
//+------------------------------------------------------------------+
void LoadState()
  {
   ArrayResize(g_links, 0);
   if(!FileIsExist(g_stateFile))
      return;
   int h = FileOpen(g_stateFile, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
     {
      LogWarn("Could not read " + g_stateFile + " (error " + IntegerToString(GetLastError()) +
              ") — links will be rebuilt from order comments.");
      return;
     }
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      string f[];
      int fc = StringSplit(line, '|', f);
      if(fc >= 2 && f[0] == "M")
         g_pinnedMaster = f[1];
      else if(fc >= 8 && f[0] == "L")
        {
         int state = (int)StringToInteger(f[3]);
         if(state != LS_OPEN && state != LS_PENDING && state != LS_DONE)
            continue;
         AddLink(f[1], (ulong)StringToInteger(f[2]), state, StringToDouble(f[4]),
                 StringToDouble(f[5]), f[6], f[7], "");
        }
     }
   FileClose(h);
   g_dirty = false;
  }

void SaveState()
  {
   if(!g_dirty)
      return;
   int h = FileOpen(g_stateFile, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
     {
      LogErr("Could not write " + g_stateFile + " (error " + IntegerToString(GetLastError()) + ")");
      return;
     }
   FileWriteString(h, "M|" + g_pinnedMaster + "\r\n");
   for(int i = 0; i < ArraySize(g_links); i++)
     {
      Link l = g_links[i];
      if(l.state != LS_OPEN && l.state != LS_PENDING && l.state != LS_DONE)
         continue;
      FileWriteString(h, StringFormat("L|%s|%I64u|%d|%.4f|%.4f|%s|%s\r\n", l.master, l.mirror, l.state,
                                      l.masterVol0, l.mirrorVol0, l.symbol, l.side));
     }
   FileClose(h);
   g_dirty = false;
  }

//+------------------------------------------------------------------+
//| Bring links up to date with this account's own state.            |
//+------------------------------------------------------------------+
//--- A filled pending order becomes a position. Its ticket normally equals the
//--- order ticket; fall back to POSITION_IDENTIFIER, then to our comment tag.
ulong FindPositionFromOrder(const ulong orderTicket, const string master)
  {
   if(PositionSelectByTicket(orderTicket))
      return(orderTicket);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if((ulong)PositionGetInteger(POSITION_IDENTIFIER) == orderTicket ||
         PositionGetString(POSITION_COMMENT) == TAG_PREFIX + master)
         return(t);
     }
   return(0);
  }

void RefreshLinks()
  {
   for(int i = ArraySize(g_links) - 1; i >= 0; i--)
     {
      if(g_links[i].state == LS_OPEN)
        {
         if(PositionSelectByTicket(g_links[i].mirror))
            continue;
         //--- Gone without us closing it: its own SL/TP, a stop-out, or by hand.
         g_links[i].state = LS_DONE;
         g_dirty = true;
         AddEvent("CLOSE", g_links[i].symbol, g_links[i].master, g_links[i].mirror,
                  "copy closed on this account (own SL/TP or manually) — will not reopen");
         g_links[i].note = "closed on this account";
        }
      else if(g_links[i].state == LS_PENDING)
        {
         if(OrderSelect(g_links[i].mirror))
            continue;
         ulong pos = FindPositionFromOrder(g_links[i].mirror, g_links[i].master);
         if(pos > 0 && PositionSelectByTicket(pos))
           {
            g_links[i].state      = LS_OPEN;
            g_links[i].mirror     = pos;
            g_links[i].mirrorVol0 = PositionGetDouble(POSITION_VOLUME);
            g_links[i].note       = "";
            g_dirty = true;
            AddEvent("FILL", g_links[i].symbol, g_links[i].master, pos,
                     StringFormat("pending copy filled, %.2f lots", g_links[i].mirrorVol0));
           }
         else
           {
            g_links[i].state = LS_DONE;
            g_dirty = true;
            AddEvent("CANCEL", g_links[i].symbol, g_links[i].master, g_links[i].mirror,
                     "pending copy removed on this account (expired or manually) — will not re-place");
            g_links[i].note = "pending removed on this account";
           }
        }
     }
  }

//--- Map a copy's comment back to its master ticket. v2 tags carry the ticket;
//--- v1 tags carry a short trade id, resolved via the snapshot's tradeId.
string MasterFromComment(const string comment)
  {
   if(StringFind(comment, TAG_PREFIX) == 0)
      return(StringSubstr(comment, StringLen(TAG_PREFIX)));
   if(StringFind(comment, LEGACY_TAG) == 0)
     {
      string shortId = StringSubstr(comment, StringLen(LEGACY_TAG));
      for(int i = 0; i < g_rowCount; i++)
         if(g_rows[i].tradeId != "-" && ShortId(g_rows[i].tradeId) == shortId)
            return(g_rows[i].ticket);
     }
   return("");
  }

string ShortId(const string id)
  {
   string s = id;
   StringReplace(s, "-", "");
   return(StringSubstr(s, 0, 16));
  }

//--- Positions/orders of ours with no link (state file lost, or placed by v1):
//--- link them to their master ticket instead of opening duplicates.
void AdoptUntracked()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || PositionGetInteger(POSITION_MAGIC) != InpMagic || FindLinkByMirror(t) >= 0)
         continue;
      string master = MasterFromComment(PositionGetString(POSITION_COMMENT));
      if(master == "" || FindLinkByMaster(master) >= 0)
         continue;
      int r = FindRow(master);
      double vol = PositionGetDouble(POSITION_VOLUME);
      string sym = PositionGetString(POSITION_SYMBOL);
      string side = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "BUY" : "SELL");
      AddLink(master, t, LS_OPEN, (r >= 0 && !g_rows[r].isOrder ? g_rows[r].volume : 0.0), vol, sym, side, "");
      AddEvent("ADOPT", sym, master, t, StringFormat("now managing existing copy (%.2f lots)", vol));
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0 || OrderGetInteger(ORDER_MAGIC) != InpMagic || FindLinkByMirror(t) >= 0)
         continue;
      string master = MasterFromComment(OrderGetString(ORDER_COMMENT));
      if(master == "" || FindLinkByMaster(master) >= 0)
         continue;
      int r = FindRow(master);
      double vol = OrderGetDouble(ORDER_VOLUME_CURRENT);
      string sym = OrderGetString(ORDER_SYMBOL);
      AddLink(master, t, LS_PENDING, (r >= 0 ? g_rows[r].volume : 0.0), vol, sym,
              OrderTypeName((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE)), "");
      AddEvent("ADOPT", sym, master, t, StringFormat("now managing existing pending copy (%.2f lots)", vol));
     }
  }

string OrderTypeName(const ENUM_ORDER_TYPE t)
  {
   switch(t)
     {
      case ORDER_TYPE_BUY_LIMIT:  return("BUY_LIMIT");
      case ORDER_TYPE_SELL_LIMIT: return("SELL_LIMIT");
      case ORDER_TYPE_BUY_STOP:   return("BUY_STOP");
      case ORDER_TYPE_SELL_STOP:  return("SELL_STOP");
      default:                    return(EnumToString(t));
     }
  }

//+------------------------------------------------------------------+
//| Per-signal risk: a multi-TP signal's legs share ONE risk budget,  |
//| split in proportion to the master's own per-leg volume. Matters   |
//| for risk and fixed sizing; the ratio modes scale master lots.     |
//+------------------------------------------------------------------+
void ComputeRiskFractions()
  {
   for(int i = 0; i < g_rowCount; i++)
     {
      g_rows[i].riskFraction = 1.0;
      if(g_rows[i].signalId == "-" || g_rows[i].signalId == "")
         continue;
      double sum = 0.0;
      int legs = 0;
      for(int j = 0; j < g_rowCount; j++)
        {
         if(g_rows[j].signalId != g_rows[i].signalId)
            continue;
         sum += MathMax(g_rows[j].volume, 0.0);
         legs++;
        }
      if(legs <= 1)
         continue;
      g_rows[i].riskFraction = (sum > 0.0) ? MathMax(g_rows[i].volume, 0.0) / sum : 1.0 / legs;
     }
  }

//+------------------------------------------------------------------+
//| One master ticket                                                |
//+------------------------------------------------------------------+
void ProcessRow(const int r)
  {
   MasterRow row = g_rows[r];
   int idx = FindLinkByMaster(row.ticket);

   // Core Principle 2 & 3: Hold Nothing While Master is Pending
   if(row.isOrder)
     {
      if(!InpCopyPending)
        {
         // If we had placed a pending order/limit for this ticket, cancel it
         if(idx >= 0)
           {
            if(g_links[idx].state == LS_PENDING && g_links[idx].mirror > 0)
              {
               if(!InpDryRun && OrderSelect(g_links[idx].mirror))
                  trade.OrderDelete(g_links[idx].mirror);
               RemoveLink(idx);
              }
           }
         SetWait(row.ticket, row.rawSymbol, "waiting for master position to fill (holding nothing while pending)");
         return;
        }
     }

   if(idx < 0)
     {
      TryCopy(row);
      return;
     }
   g_links[idx].misses = 0;

   switch(g_links[idx].state)
     {
      case LS_OPEN:
         //--- A master ORDER whose copy already filled here: follow its SL/TP only.
         SyncPosition(idx, row, !row.isOrder);
         break;
      case LS_PENDING:
         //--- Master position whose copy is still pending here: keep our entry
         //--- price, follow SL/TP, wait for the fill.
         SyncPending(idx, row, !row.isOrder);
         break;
      default:
         break; // SKIPPED / DONE / DRY: nothing to do
     }
  }

void TryCopy(const MasterRow &row)
  {
   bool manual = (row.tradeId == "-" || row.tradeId == "");

   //--- Configuration checks
   if(!row.isOrder && !InpCopyOpens)  { SetWait(row.ticket, row.rawSymbol, "copying new positions is off (InpCopyOpens)"); return; }
   if(row.isOrder && !InpCopyPending) { SetWait(row.ticket, row.rawSymbol, "waiting for master position to fill (InpCopyPending=false)"); return; }
   if(manual && !InpCopyManual)       { SetWait(row.ticket, row.rawSymbol, "manual master trade (InpCopyManual=false)"); return; }
   if(InpAllowedSymbols != "" && !IsSymbolAllowed(row.symbol) && !IsSymbolAllowed(row.rawSymbol))
     {
      SetWait(row.ticket, row.rawSymbol, "symbol not in InpAllowedSymbols");
      return;
     }

   //--- Permanent for this ticket (kept in memory; re-evaluated after a restart).
   if(row.isOrder && StringFind(row.side, "STOP_LIMIT") >= 0)
     {
      Skip(row, "stop-limit orders are not supported");
      return;
     }

   string sym = MapSymbol(row);
   if(sym == "")
     {
      Skip(row, "symbol " + row.rawSymbol + " not found on this broker (set InpSymbolMap)");
      return;
     }

   //--- Transient: re-checked every poll.
   if(g_halted)
     {
      SetWait(row.ticket, sym, "daily loss limit reached — no new copies today");
      return;
     }
   if(InpMaxPositions > 0 && CountEaPositions() >= InpMaxPositions)
     {
      SetWait(row.ticket, sym, "InpMaxPositions reached");
      return;
     }

   bool   isLong = (StringFind(row.side, "BUY") == 0);
   double ask    = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid    = SymbolInfoDouble(sym, SYMBOL_BID);
   double point  = SymbolInfoDouble(sym, SYMBOL_POINT);
   int    dg     = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(ask <= 0.0 || bid <= 0.0 || point <= 0.0)
     {
      SetWait(row.ticket, sym, "no price for " + sym + " yet");
      return;
     }

   double currentPrice = isLong ? ask : bid;
   double spreadPrice  = ask - bid;

   //--- Max spread check for new entries
   if(!row.isOrder && InpMaxSpreadPoints > 0.0 && (spreadPrice / point) > InpMaxSpreadPoints)
     {
      SetWait(row.ticket, sym, StringFormat("spread %.0f pts > InpMaxSpreadPoints", spreadPrice / point));
      return;
     }

   //--- Pending order path (when InpCopyPending is true)
   if(row.isOrder)
     {
      double ref = row.price;
      string sizeNote = "";
      double lots = CalculateLots(sym, row, ref, isLong, sizeNote);
      if(lots <= 0.0)
        {
         SetWait(row.ticket, sym, sizeNote != "" ? sizeNote : "sizing refused");
         return;
        }

      double sl = row.sl > 0.0 ? NormalizeDouble(row.sl, dg) : 0.0;
      double tp = row.tp > 0.0 ? NormalizeDouble(row.tp, dg) : 0.0;
      string comment = TAG_PREFIX + row.ticket;
      string what    = StringFormat("%s %.2f lots%s", row.side, lots, sizeNote != "" ? " — " + sizeNote : "");

      if(InpDryRun)
        {
         AddLink(row.ticket, 0, LS_DRY, row.volume, lots, sym, row.side, "dry run: would place " + what);
         AddEvent("DRY", sym, row.ticket, 0, "would place " + what);
         return;
        }

      trade.SetTypeFillingBySymbol(sym);
      double price = NormalizeDouble(row.price, dg);
      string kind;
      bool   ok;
      if(isLong)
        {
         if(price < ask) { kind = "BUY_LIMIT"; ok = trade.BuyLimit(lots, price, sym, sl, tp, ORDER_TIME_GTC, 0, comment); }
         else            { kind = "BUY_STOP";  ok = trade.BuyStop (lots, price, sym, sl, tp, ORDER_TIME_GTC, 0, comment); }
        }
      else
        {
         if(price > bid) { kind = "SELL_LIMIT"; ok = trade.SellLimit(lots, price, sym, sl, tp, ORDER_TIME_GTC, 0, comment); }
         else            { kind = "SELL_STOP";  ok = trade.SellStop (lots, price, sym, sl, tp, ORDER_TIME_GTC, 0, comment); }
        }
      if(ok)
        {
         ulong t = trade.ResultOrder();
         AddLink(row.ticket, t, LS_PENDING, row.volume, lots, sym, kind, "");
         AddEvent("PLACE", sym, row.ticket, t, StringFormat("%s %.2f lots @ %s sl=%s tp=%s", kind, lots,
                  DoubleToString(price, dg), DoubleToString(sl, dg), DoubleToString(tp, dg)));
        }
      else
         SetWait(row.ticket, sym, StringFormat("%s rejected: %d %s", kind, trade.ResultRetcode(), trade.ResultRetcodeDescription()));
      return;
     }

   //==================================================================
   // MASTER RUNNING POSITION EVALUATION
   //==================================================================

   // Step 3: Opportunity & Viability Check ("Chance Gone")
   // 1. Stop Breached check
   if(row.sl > 0.0)
     {
      if(isLong && bid <= row.sl + point / 2.0)
        {
         Skip(row, "master SL already breached on follower broker");
         return;
        }
      if(!isLong && ask >= row.sl - point / 2.0)
        {
         Skip(row, "master SL already breached on follower broker");
         return;
        }
     }

   // 2. TP Already Hit / Touched check
   if(row.tp > 0.0)
     {
      if(isLong && bid >= row.tp - point / 2.0)
        {
         Skip(row, "master TP target already hit — momentum completed");
         return;
        }
      if(!isLong && ask <= row.tp + point / 2.0)
        {
         Skip(row, "master TP target already hit — momentum completed");
         return;
        }
     }

   // 3. Remaining R:R Floor check
   double initSl = (row.initSl > 0.0) ? row.initSl : row.sl;
   double initialRiskUnit = (initSl > 0.0) ? MathAbs(row.price - initSl) : 0.0;
   if(initialRiskUnit < point)
      initialRiskUnit = (row.sl > 0.0) ? MathAbs(row.price - row.sl) : 0.0;

   if(InpMinRemainingRR > 0.0 && row.tp > 0.0 && row.sl > 0.0 && initialRiskUnit > point)
     {
      double reward = MathAbs(row.tp - currentPrice);
      double risk   = MathMax(MathAbs(currentPrice - row.sl), initialRiskUnit);
      double remainingRR = (risk > 0.0) ? (reward / risk) : 0.0;

      // Multi-leg check: if part of a multi-leg signal, check if later legs have higher target
      if(row.signalId != "" && row.signalId != "-")
        {
         double maxTp = row.tp;
         for(int j = 0; j < g_rowCount; j++)
           {
            if(g_rows[j].signalId == row.signalId && g_rows[j].tp > 0.0)
              {
               if((isLong && g_rows[j].tp > maxTp) || (!isLong && g_rows[j].tp < maxTp))
                  maxTp = g_rows[j].tp;
              }
           }
         double maxReward = MathAbs(maxTp - currentPrice);
         double maxRR = (risk > 0.0) ? (maxReward / risk) : 0.0;
         if(maxRR > remainingRR)
            remainingRR = maxRR;
        }

      if(remainingRR < InpMinRemainingRR)
        {
         Skip(row, StringFormat("insufficient remaining R:R (%.2fR < %.2fR)", remainingRR, InpMinRemainingRR));
         return;
        }
     }

   // Step 4: Anti-Slippage Protection (Tolerance & Limit Fallback)
   // Adverse price movement: positive means follower price is worse than master fill
   double adverse = isLong ? (ask - row.price) : (row.price - bid);

   // Slippage tolerance: max(0.15 * initialRiskUnit, currentSpread)
   double tol = spreadPrice;
   if(initialRiskUnit > point && InpSlippageRiskTolerance > 0.0)
     {
      double riskTol = InpSlippageRiskTolerance * initialRiskUnit;
      if(riskTol > tol)
         tol = riskTol;
     }
   if(InpMaxEntryDeviationPts > 0)
     {
      double devPts = InpMaxEntryDeviationPts * point;
      if(tol > devPts)
         tol = devPts;
     }

   // If price is better or within tolerance: Execute immediate MARKET order (Spec Step 4)
   bool enterAtMarket = (adverse <= tol);

   // Sizing reference price
   double ref = enterAtMarket ? currentPrice : row.price;
   string sizeNote = "";
   double lots = CalculateLots(sym, row, ref, isLong, sizeNote);
   if(lots <= 0.0)
     {
      SetWait(row.ticket, sym, sizeNote != "" ? sizeNote : "sizing refused");
      return;
     }

   // Dynamic spread compensation on Stop Loss
   double sl = 0.0;
   if(row.sl > 0.0)
     {
      if(InpSpreadMultiplier > 0.0)
         sl = isLong ? (row.sl - InpSpreadMultiplier * spreadPrice) : (row.sl + InpSpreadMultiplier * spreadPrice);
      else
         sl = row.sl;
      sl = NormalizeDouble(sl, dg);
     }
   double tp = row.tp > 0.0 ? NormalizeDouble(row.tp, dg) : 0.0;
   string comment = TAG_PREFIX + row.ticket;
   string what = StringFormat("%s %.2f lots%s%s", row.side, lots,
                              row.riskFraction < 0.999 ? StringFormat(" (%.0f%% of signal risk)", row.riskFraction * 100.0) : "",
                              sizeNote != "" ? " — " + sizeNote : "");

   if(InpDryRun)
     {
      string desc = enterAtMarket ? ("would open " + what)
                                  : StringFormat("would place resting LIMIT %s %.2f lots @ %s (slippage %.1f pts > tol %.1f pts)",
                                                 isLong ? "BUY_LIMIT" : "SELL_LIMIT", lots, DoubleToString(row.price, dg),
                                                 adverse / point, tol / point);
      AddLink(row.ticket, 0, LS_DRY, row.volume, lots, sym, row.side, "dry run: " + desc);
      AddEvent("DRY", sym, row.ticket, 0, desc);
      return;
     }

   trade.SetTypeFillingBySymbol(sym);

   // Enter at market if within tolerance
   if(enterAtMarket)
     {
      bool ok = isLong ? trade.Buy(lots, sym, 0.0, sl, tp, comment) : trade.Sell(lots, sym, 0.0, sl, tp, comment);
      if(ok)
        {
         ulong t = FindPositionFromOrder(trade.ResultOrder(), row.ticket);
         if(t == 0)
            t = trade.ResultOrder();
         AddLink(row.ticket, t, LS_OPEN, row.volume, lots, sym, row.side, "");
         AddEvent("OPEN", sym, row.ticket, t, StringFormat("%s @ %s sl=%s tp=%s", what,
                  DoubleToString(trade.ResultPrice(), dg), DoubleToString(sl, dg), DoubleToString(tp, dg)));
        }
      else
         SetWait(row.ticket, sym, StringFormat("open rejected: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription()));
      return;
     }

   // Adverse slippage > tolerance: Place resting LIMIT order at master fill price (do not chase)
   double limitPrice = NormalizeDouble(row.price, dg);
   string kind = isLong ? "BUY_LIMIT" : "SELL_LIMIT";
   bool okLimit = false;

   if(isLong)
     {
      if(limitPrice < ask)
         okLimit = trade.BuyLimit(lots, limitPrice, sym, sl, tp, ORDER_TIME_GTC, 0, comment);
      else
         okLimit = trade.Buy(lots, sym, 0.0, sl, tp, comment); // Price pulled back to market
     }
   else
     {
      if(limitPrice > bid)
         okLimit = trade.SellLimit(lots, limitPrice, sym, sl, tp, ORDER_TIME_GTC, 0, comment);
      else
         okLimit = trade.Sell(lots, sym, 0.0, sl, tp, comment); // Price pulled back to market
     }

   if(okLimit)
     {
      ulong t = trade.ResultOrder();
      ulong pos = FindPositionFromOrder(t, row.ticket);
      if(pos > 0)
        {
         AddLink(row.ticket, pos, LS_OPEN, row.volume, lots, sym, row.side, "");
         AddEvent("OPEN", sym, row.ticket, pos, StringFormat("%s @ %s sl=%s tp=%s", what,
                  DoubleToString(trade.ResultPrice(), dg), DoubleToString(sl, dg), DoubleToString(tp, dg)));
        }
      else
        {
         AddLink(row.ticket, t, LS_PENDING, row.volume, lots, sym, kind, "resting limit at master fill");
         AddEvent("PLACE", sym, row.ticket, t, StringFormat("resting limit %s %.2f lots @ %s (slippage %.1f pts > tol %.1f pts)",
                  kind, lots, DoubleToString(limitPrice, dg), adverse / point, tol / point));
        }
     }
   else
     {
      SetWait(row.ticket, sym, StringFormat("limit %s rejected: %d %s", kind, trade.ResultRetcode(), trade.ResultRetcodeDescription()));
     }
  }

void Skip(const MasterRow &row, const string note)
  {
   AddLink(row.ticket, 0, LS_SKIPPED, row.volume, 0.0, row.rawSymbol, row.side, note);
   AddEvent("SKIP", row.rawSymbol, row.ticket, 0, note);
  }

//+------------------------------------------------------------------+
//| Keep an open copy matching the master: SL/TP and partial closes. |
//+------------------------------------------------------------------+
int VolumeDigits(const double step)
  {
   int d = 0;
   while(d < 8 && MathAbs(step * MathPow(10, d) - MathRound(step * MathPow(10, d))) > 1e-8)
      d++;
   return(d);
  }

void SyncPosition(const int idx, const MasterRow &row, const bool allowPartial)
  {
   ulong t = g_links[idx].mirror;
   if(!PositionSelectByTicket(t))
      return; // RefreshLinks picks this up next poll

   string sym   = PositionGetString(POSITION_SYMBOL);
   int    dg    = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   double curSL = PositionGetDouble(POSITION_SL);
   double curTP = PositionGetDouble(POSITION_TP);
   double vol   = PositionGetDouble(POSITION_VOLUME);
   bool   isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   string note  = "";
   bool   isErr = false;

   //--- SL / TP synchronization (Tighten-only SL & missing SL/TP reattachment)
   if(InpCopySLTP)
     {
      double masterSL = row.sl > 0.0 ? NormalizeDouble(row.sl, dg) : 0.0;
      double masterTP = row.tp > 0.0 ? NormalizeDouble(row.tp, dg) : 0.0;

      // Apply spread buffer on masterSL if configured
      if(masterSL > 0.0 && InpSpreadMultiplier > 0.0)
        {
         double spread = SymbolInfoDouble(sym, SYMBOL_ASK) - SymbolInfoDouble(sym, SYMBOL_BID);
         masterSL = isBuy ? (masterSL - InpSpreadMultiplier * spread) : (masterSL + InpSpreadMultiplier * spread);
         masterSL = NormalizeDouble(masterSL, dg);
        }

      double wantSL = curSL;
      double wantTP = curTP;

      // Tighten-only SL safety rule:
      if(masterSL > 0.0)
        {
         if(curSL <= 0.0)
           {
            // Missing SL reattachment
            wantSL = masterSL;
           }
         else if(isBuy)
           {
            // For BUY, tighter means HIGHER stop loss
            if(masterSL > curSL + point / 2.0)
               wantSL = masterSL;
           }
         else
           {
            // For SELL, tighter means LOWER stop loss
            if(masterSL < curSL - point / 2.0)
               wantSL = masterSL;
           }
        }

      // TP reattachment / update
      if(masterTP > 0.0)
        {
         if(curTP <= 0.0 || MathAbs(curTP - masterTP) > point / 2.0)
            wantTP = masterTP;
        }

      if(MathAbs(curSL - wantSL) > point / 2.0 || MathAbs(curTP - wantTP) > point / 2.0)
        {
         if(InpDryRun)
            note = StringFormat("dry run: would set SL %s->%s TP %s->%s", DoubleToString(curSL, dg),
                                DoubleToString(wantSL, dg), DoubleToString(curTP, dg), DoubleToString(wantTP, dg));
         else if(trade.PositionModify(t, wantSL, wantTP))
            AddEvent("MODIFY", sym, row.ticket, t, StringFormat("SL %s->%s  TP %s->%s", DoubleToString(curSL, dg),
                     DoubleToString(wantSL, dg), DoubleToString(curTP, dg), DoubleToString(wantTP, dg)));
         else
           {
            note  = StringFormat("SL/TP update rejected: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
            isErr = true;
           }
        }
     }

   //--- Partial close, as a proportion of where each side started.
   if(allowPartial && InpCopyPartials && note == "")
     {
      if(g_links[idx].masterVol0 <= 0.0)
        {
         g_links[idx].masterVol0 = row.volume; // adopted without a baseline: start from now
         g_links[idx].mirrorVol0 = vol;
         g_dirty = true;
        }
      else if(row.volume > g_links[idx].masterVol0 + 1e-9)
        {
         //--- Master grew (netting master added to it): rebase, never add here.
         g_links[idx].masterVol0 = row.volume;
         g_links[idx].mirrorVol0 = vol;
         g_dirty = true;
        }
      else if(row.volume < g_links[idx].masterVol0 - 1e-9)
        {
         double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
         double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
         if(step <= 0.0)
            step = 0.01;
         int    vd     = VolumeDigits(step);
         double target = g_links[idx].mirrorVol0 * row.volume / g_links[idx].masterVol0;
         target = MathRound(target / step) * step;
         if(target < vmin)
            target = vmin; // master still holds some: keep the broker minimum
         double reduce = NormalizeDouble(MathFloor((vol - target) / step + 1e-6) * step, vd);
         if(reduce >= step - 1e-9)
           {
            if(InpDryRun)
               note = StringFormat("dry run: would close %.2f of %.2f lots (master %.2f->%.2f)",
                                   reduce, vol, g_links[idx].masterVol0, row.volume);
            else
              {
               trade.SetTypeFillingBySymbol(sym);
               if(trade.PositionClosePartial(t, reduce))
                  AddEvent("PARTIAL", sym, row.ticket, t, StringFormat("closed %.2f of %.2f lots (master now %.2f of %.2f)",
                           reduce, vol, row.volume, g_links[idx].masterVol0));
               else
                 {
                  note  = StringFormat("partial close rejected: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
                  isErr = true;
                 }
              }
           }
        }
     }

   g_links[idx].inSync = (note == "");
   SetLinkNote(idx, note, isErr);
  }

//+------------------------------------------------------------------+
//| Keep a pending copy matching the master order (price, SL, TP).   |
//| keepPrice: the master already FILLED — don't move our entry.     |
//+------------------------------------------------------------------+
void SyncPending(const int idx, const MasterRow &row, const bool keepPrice)
  {
   ulong t = g_links[idx].mirror;
   if(!OrderSelect(t))
      return;

   string sym      = OrderGetString(ORDER_SYMBOL);
   int    dg       = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double point    = SymbolInfoDouble(sym, SYMBOL_POINT);
   double curPrice = OrderGetDouble(ORDER_PRICE_OPEN);
   double curSL    = OrderGetDouble(ORDER_SL);
   double curTP    = OrderGetDouble(ORDER_TP);

   double wantPrice = keepPrice ? curPrice : NormalizeDouble(row.price, dg);
   double wantSL    = InpCopySLTP ? (row.sl > 0.0 ? NormalizeDouble(row.sl, dg) : 0.0) : curSL;
   double wantTP    = InpCopySLTP ? (row.tp > 0.0 ? NormalizeDouble(row.tp, dg) : 0.0) : curTP;
   string note      = "";
   bool   isErr     = false;

   if(MathAbs(curPrice - wantPrice) > point / 2.0 || MathAbs(curSL - wantSL) > point / 2.0 ||
      MathAbs(curTP - wantTP) > point / 2.0)
     {
      if(InpDryRun)
         note = StringFormat("dry run: would move order to %s sl=%s tp=%s", DoubleToString(wantPrice, dg),
                             DoubleToString(wantSL, dg), DoubleToString(wantTP, dg));
      else if(trade.OrderModify(t, wantPrice, wantSL, wantTP, ORDER_TIME_GTC, 0, 0))
         AddEvent("MODIFY", sym, row.ticket, t, StringFormat("order %s->%s  SL %s->%s  TP %s->%s",
                  DoubleToString(curPrice, dg), DoubleToString(wantPrice, dg), DoubleToString(curSL, dg),
                  DoubleToString(wantSL, dg), DoubleToString(curTP, dg), DoubleToString(wantTP, dg)));
      else
        {
         note  = StringFormat("order update rejected: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
         isErr = true;
        }
     }
   //--- (Master filled while ours is still pending shows as "awaiting fill" on
   //--- the dashboard from the link state itself; nothing to note here.)
   g_links[idx].inSync = (note == "");
   SetLinkNote(idx, note, isErr);
  }

//+------------------------------------------------------------------+
//| Master tickets that disappeared: close / cancel after N polls.   |
//+------------------------------------------------------------------+
void ProcessMissing()
  {
   for(int i = ArraySize(g_links) - 1; i >= 0; i--)
     {
      if(FindRow(g_links[i].master) >= 0)
         continue;

      g_links[i].misses++;
      int   state = g_links[i].state;
      ulong t     = g_links[i].mirror;

      if(state == LS_SKIPPED || state == LS_DRY)
        {
         RemoveLink(i);
         continue;
        }
      if(state == LS_DONE)
        {
         //--- Forget it once nothing of ours is left for that ticket.
         if(t == 0 || (!PositionSelectByTicket(t) && !OrderSelect(t)))
            RemoveLink(i);
         continue;
        }

      if(g_links[i].misses < InpCloseConfirmPolls)
        {
         g_links[i].inSync = false;
         g_links[i].note   = StringFormat("gone from master — confirming (%d/%d)", g_links[i].misses, InpCloseConfirmPolls);
         continue;
        }

      string sym = g_links[i].symbol;
      string master = g_links[i].master;

      if(state == LS_PENDING)
        {
         //--- Always cancel: a pending the master no longer has must not fill later.
         if(!OrderSelect(t))
           {
            RemoveLink(i);
            continue;
           }
         if(InpDryRun)
           {
            SetLinkNote(i, "dry run: would cancel (master order gone)", false);
            continue;
           }
         if(trade.OrderDelete(t))
           {
            AddEvent("CANCEL", sym, master, t, "master order gone — pending copy cancelled");
            RemoveLink(i);
           }
         else
            SetLinkNote(i, StringFormat("cancel rejected: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription()), true);
         continue;
        }

      //--- LS_OPEN
      if(!PositionSelectByTicket(t))
        {
         RemoveLink(i);
         continue;
        }
      if(!InpCopyCloses)
        {
         g_links[i].state = LS_DONE;
         g_dirty = true;
         AddEvent("WARN", sym, master, t, "master closed — left open here (InpCopyCloses=false)");
         g_links[i].note = "master closed; left open (InpCopyCloses=false)";
         continue;
        }
      if(InpDryRun)
        {
         SetLinkNote(i, "dry run: would close (master closed)", false);
         continue;
        }
      double vol    = PositionGetDouble(POSITION_VOLUME);
      double profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      trade.SetTypeFillingBySymbol(sym);
      if(trade.PositionClose(t, InpMaxSlippage))
        {
         AddEvent("CLOSE", sym, master, t, StringFormat("master closed — closed %.2f lots, P/L %.2f", vol, profit));
         RemoveLink(i);
        }
      else
         SetLinkNote(i, StringFormat("close rejected: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription()), true);
     }
  }

void ComputeSyncStats()
  {
   g_synced = 0;
   g_issues = 0;
   for(int i = 0; i < g_rowCount; i++)
     {
      int idx = FindLinkByMaster(g_rows[i].ticket);
      if(idx < 0)
        {
         g_issues++;
         continue;
        }
      int s = g_links[idx].state;
      if(s == LS_OPEN || s == LS_PENDING)
        {
         if(g_links[idx].inSync) g_synced++; else g_issues++;
        }
     }
   for(int i = ArraySize(g_links) - 1; i >= 0; i--)
      if((g_links[i].state == LS_OPEN || g_links[i].state == LS_PENDING) && FindRow(g_links[i].master) < 0)
         g_issues++;
  }

//+------------------------------------------------------------------+
//| Sizing                                                           |
//+------------------------------------------------------------------+
double CalculateLots(const string sym, const MasterRow &row, const double entry, const bool isLong, string &note)
  {
   double lots = 0.0;
   bool   riskSized = false;
   double point = SymbolInfoDouble(sym, SYMBOL_POINT);

   // Sizing protection: size against initial stop loss to avoid lot explosion on breakeven stops
   double calcSl = (row.initSl > 0.0) ? row.initSl : row.sl;

   if(InpSizingMode == SIZE_RISK_PERCENT && calcSl > 0.0)
     {
      // If stop distance is virtually zero (< 5 points, e.g. at breakeven), fall back to equity ratio
      if(point > 0.0 && MathAbs(entry - calcSl) <= 5.0 * point)
        {
         if(g_masterEquity > 0.0)
           {
            lots = row.volume * AccountInfoDouble(ACCOUNT_EQUITY) / g_masterEquity;
            note = "master SL at breakeven — sized by equity ratio";
           }
         else
           {
            lots = row.volume;
            note = "master SL at breakeven — matched master lots";
           }
        }
      else
        {
         double riskMoney  = AccountInfoDouble(ACCOUNT_BALANCE) * (InpRiskPercent * row.riskFraction / 100.0);
         double lossPerLot = 0.0;
         if(!OrderCalcProfit(isLong ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, 1.0, entry, calcSl, lossPerLot))
           {
            note = "OrderCalcProfit failed (error " + IntegerToString(GetLastError()) + ")";
            return(0.0);
           }
         lossPerLot = MathAbs(lossPerLot);
         if(lossPerLot <= 0.0)
           {
            note = "broker reports zero loss per lot";
            return(0.0);
           }
         lots = riskMoney / lossPerLot;
         riskSized = true;
        }
     }
   else if(InpSizingMode == SIZE_RISK_PERCENT || InpSizingMode == SIZE_EQUITY_RATIO)
     {
      if(InpSizingMode == SIZE_RISK_PERCENT)
         note = "master has no SL — sized by equity ratio";
      if(g_masterEquity <= 0.0)
        {
         note = "master equity unknown — cannot size by equity ratio";
         return(0.0);
        }
      double mult = (InpSizingMode == SIZE_EQUITY_RATIO) ? InpLotMultiplier : 1.0;
      lots = row.volume * AccountInfoDouble(ACCOUNT_EQUITY) / g_masterEquity * mult;
     }
   else if(InpSizingMode == SIZE_LOT_MULTIPLIER)
      lots = row.volume * InpLotMultiplier;
   else
      lots = InpFixedLot * row.riskFraction;

   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step <= 0.0)
      step = 0.01;
   int vd = VolumeDigits(step);

   lots = NormalizeDouble(MathFloor(lots / step + 1e-9) * step, vd);
   if(InpMaxLot > 0.0 && lots > InpMaxLot)
      lots = NormalizeDouble(MathFloor(InpMaxLot / step + 1e-9) * step, vd);
   if(vmax > 0.0 && lots > vmax)
      lots = vmax;
   if(lots < vmin)
     {
      note = StringFormat("sized %.3f lots, below broker minimum %.2f", lots, vmin);
      return(0.0);
     }

   //--- Re-price the risk at the lot size actually being sent.
   if(riskSized && calcSl > 0.0)
     {
      double riskMoney  = AccountInfoDouble(ACCOUNT_BALANCE) * (InpRiskPercent * row.riskFraction / 100.0);
      double actualRisk = 0.0;
      if(!OrderCalcProfit(isLong ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, lots, entry, calcSl, actualRisk))
        {
         note = "post-sizing risk check failed";
         return(0.0);
        }
      actualRisk = MathAbs(actualRisk);
      if(riskMoney > 0.0 && actualRisk > riskMoney * InpMaxRiskOvershoot)
        {
         note = StringFormat("%.2f lots would risk %.2f vs target %.2f (> %.1fx)", lots, actualRisk, riskMoney, InpMaxRiskOvershoot);
         return(0.0);
        }
     }

   double margin = 0.0;
   if(OrderCalcMargin(isLong ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, lots, entry, margin) &&
      margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
     {
      note = StringFormat("%.2f lots needs %.2f margin, %.2f free", lots, margin, AccountInfoDouble(ACCOUNT_MARGIN_FREE));
      return(0.0);
     }
   return(lots);
  }

int CountEaPositions()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t != 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         n++;
     }
   return(n);
  }

//+------------------------------------------------------------------+
//| Daily loss limit — stops NEW copies only. Closes, partials and    |
//| SL/TP changes keep following the master (they only cut risk).     |
//+------------------------------------------------------------------+
void ResetDailyEquityBaseline()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   g_dayStamp       = dt.day_of_year;
   g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_halted         = false;
  }

void CheckDailyLossLimit()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != g_dayStamp)
     {
      ResetDailyEquityBaseline();
      Log("New trading day — daily loss baseline reset.");
     }
   if(InpMaxDailyLossPct <= 0.0 || g_dayStartEquity <= 0.0)
      return;
   double lossPct = (g_dayStartEquity - AccountInfoDouble(ACCOUNT_EQUITY)) / g_dayStartEquity * 100.0;
   if(lossPct >= InpMaxDailyLossPct && !g_halted)
     {
      g_halted = true;
      AddEvent("WARN", "", "", 0, StringFormat("daily loss limit hit (-%.2f%%, limit %.2f%%): no new copies today; "
               "existing copies still follow the master", lossPct, InpMaxDailyLossPct));
     }
  }

//+------------------------------------------------------------------+
//| Symbol mapping                                                   |
//+------------------------------------------------------------------+
string EffectiveSuffix() { return(InpSymbolSuffix != "" ? InpSymbolSuffix : g_detectedSuffix); }
string EffectivePrefix() { return(InpSymbolPrefix != "" ? InpSymbolPrefix : g_detectedPrefix); }

bool IsSymbolAllowed(const string sym)
  {
   string list[];
   int n = StringSplit(InpAllowedSymbols, ',', list);
   for(int i = 0; i < n; i++)
     {
      string s = list[i];
      StringTrimLeft(s);
      StringTrimRight(s);
      if(s == sym)
         return(true);
     }
   return(false);
  }

string MapSymbol(const MasterRow &row)
  {
   if(InpSymbolMap != "")
     {
      string map = InpSymbolMap;
      StringReplace(map, ";", ",");
      string pairs[];
      int n = StringSplit(map, ',', pairs);
      for(int i = 0; i < n; i++)
        {
         string kv[];
         if(StringSplit(pairs[i], '=', kv) != 2)
            continue;
         string k = kv[0], v = kv[1];
         StringTrimLeft(k); StringTrimRight(k); StringTrimLeft(v); StringTrimRight(v);
         if(StringCompare(k, row.rawSymbol, false) == 0 || StringCompare(k, row.symbol, false) == 0)
            return(SymbolSelect(v, true) ? v : "");
        }
     }
   return(ResolveSymbol(row.symbol, row.rawSymbol));
  }

string ResolveSymbol(const string pair, const string raw)
  {
   string candidate = EffectivePrefix() + pair + EffectiveSuffix();
   if(SymbolSelect(candidate, true))
      return(candidate);
   if(raw != "" && raw != "-" && SymbolSelect(raw, true))
      return(raw);
   if(SymbolSelect(pair, true))
      return(pair);
   int total = SymbolsTotal(false);
   for(int i = 0; i < total; i++)
     {
      string name = SymbolName(i, false);
      if(StringFind(name, pair) >= 0 && SymbolSelect(name, true))
         return(name);
     }
   return("");
  }

void DetectSymbolAffixes()
  {
   string probe = "EURUSD";
   int total = SymbolsTotal(false);
   for(int i = 0; i < total; i++)
     {
      string name = SymbolName(i, false);
      int    pos  = StringFind(name, probe);
      if(pos < 0)
         continue;
      g_detectedPrefix = StringSubstr(name, 0, pos);
      g_detectedSuffix = StringSubstr(name, pos + StringLen(probe));
      if(g_detectedPrefix != "" || g_detectedSuffix != "")
         Log("Detected broker symbol format: prefix='" + g_detectedPrefix +
             "' suffix='" + g_detectedSuffix + "' (from " + name + ")");
      return;
     }
   LogWarn("Could not auto-detect symbol format (no EURUSD variant found). "
           "Set InpSymbolSuffix/InpSymbolPrefix or InpSymbolMap if your broker uses them.");
  }

//+------------------------------------------------------------------+
//| Status report -> dashboard (/api/ea/report)                      |
//+------------------------------------------------------------------+
string Js(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\n", " ");
   StringReplace(s, "\r", " ");
   StringReplace(s, "\t", " ");
   return("\"" + s + "\"");
  }

string Jn(const double v, const int dp) { return(DoubleToString(v, dp)); }
string Jb(const bool v) { return(v ? "true" : "false"); }

string LinkJson(const Link &l)
  {
   double vol = 0.0, price = 0.0, sl = 0.0, tp = 0.0, profit = 0.0;
   if(l.state == LS_OPEN && PositionSelectByTicket(l.mirror))
     {
      vol    = PositionGetDouble(POSITION_VOLUME);
      price  = PositionGetDouble(POSITION_PRICE_OPEN);
      sl     = PositionGetDouble(POSITION_SL);
      tp     = PositionGetDouble(POSITION_TP);
      profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
     }
   else if(l.state == LS_PENDING && OrderSelect(l.mirror))
     {
      vol   = OrderGetDouble(ORDER_VOLUME_CURRENT);
      price = OrderGetDouble(ORDER_PRICE_OPEN);
      sl    = OrderGetDouble(ORDER_SL);
      tp    = OrderGetDouble(ORDER_TP);
     }
   else if(l.state == LS_DRY)
      vol = l.mirrorVol0;

   return("{\"master\":" + Js(l.master) +
          ",\"mirror\":" + Js(l.mirror > 0 ? StringFormat("%I64u", l.mirror) : "") +
          ",\"state\":" + Js(StateName(l.state)) +
          ",\"symbol\":" + Js(l.symbol) +
          ",\"side\":" + Js(l.side) +
          ",\"volume\":" + Jn(vol, 3) +
          ",\"price\":" + Jn(price, 6) +
          ",\"sl\":" + Jn(sl, 6) +
          ",\"tp\":" + Jn(tp, 6) +
          ",\"profit\":" + Jn(profit, 2) +
          ",\"inSync\":" + Jb(l.inSync) +
          ",\"note\":" + Js(l.note) + "}");
  }

string BuildReport()
  {
   string links = "";
   for(int i = 0; i < ArraySize(g_links); i++)
      links += (links == "" ? "" : ",") + LinkJson(g_links[i]);
   for(int i = 0; i < ArraySize(g_waitKeys); i++)
      links += (links == "" ? "" : ",") + "{\"master\":" + Js(g_waitKeys[i]) +
               ",\"state\":\"WAIT\",\"inSync\":false,\"note\":" + Js(g_waitNotes[i]) + "}";

   string events = "";
   for(int i = 0; i < g_evCount; i++)
      events += (events == "" ? "" : ",") + "{\"type\":" + Js(g_evType[i]) + ",\"symbol\":" + Js(g_evSymbol[i]) +
                ",\"master\":" + Js(g_evMaster[i]) + ",\"mirror\":" + Js(g_evMirror[i]) +
                ",\"msg\":" + Js(g_evMsg[i]) + "}";

   return("{\"eaVersion\":" + Js(EA_VERSION) +
          ",\"login\":" + Js(IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))) +
          ",\"server\":" + Js(AccountInfoString(ACCOUNT_SERVER)) +
          ",\"broker\":" + Js(AccountInfoString(ACCOUNT_COMPANY)) +
          ",\"name\":" + Js(AccountInfoString(ACCOUNT_NAME)) +
          ",\"currency\":" + Js(AccountInfoString(ACCOUNT_CURRENCY)) +
          ",\"leverage\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE)) +
          ",\"balance\":" + Jn(AccountInfoDouble(ACCOUNT_BALANCE), 2) +
          ",\"equity\":" + Jn(AccountInfoDouble(ACCOUNT_EQUITY), 2) +
          ",\"margin\":" + Jn(AccountInfoDouble(ACCOUNT_MARGIN), 2) +
          ",\"freeMargin\":" + Jn(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) +
          ",\"mode\":" + Js(InpDryRun ? "DRY" : "LIVE") +
          ",\"halted\":" + Jb(g_halted) +
          ",\"sizing\":" + Js(SizingLabel()) +
          ",\"pollSeconds\":" + IntegerToString(InpPollSeconds) +
          ",\"reportSeconds\":" + IntegerToString(InpReportSeconds) +
          ",\"feedOk\":" + Jb(g_feedOk && !g_masterMismatch) +
          ",\"pollFailures\":" + IntegerToString(g_pollFailures) +
          ",\"lastError\":" + Js(g_lastError) +
          ",\"masterLogin\":" + Js(g_masterLogin) +
          ",\"links\":[" + links + "]" +
          ",\"events\":[" + events + "]}");
  }

void MaybeReport(const bool force)
  {
   if(InpReportSeconds <= 0)
      return;
   ulong now = GetTickCount64();
   ulong since = now - g_lastReportMs;
   //--- On schedule, or sooner (>= 3s) when there are actions to show.
   if(!force && since < (ulong)InpReportSeconds * 1000 && !(g_evCount > 0 && since >= 3000))
      return;
   g_lastReportMs = now;

   char   data[], result[];
   string resultHeaders;
   StringToCharArray(BuildReport(), data, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(data, ArraySize(data) - 1); // drop the trailing NUL
   string headers = "Content-Type: application/json\r\nX-EA-Key: " + InpApiKey + "\r\n";

   ResetLastError();
   int status = WebRequest("POST", InpApiUrl + "/api/ea/report", headers, InpTimeoutMs, data, result, resultHeaders);
   if(status == 200)
     {
      g_evCount = 0; // delivered
      return;
     }
   //--- Keep the events for the next attempt; the copier itself carries on.
   LogWarn(status == -1 ? "Status report failed (WebRequest error " + IntegerToString(GetLastError()) + ")"
                        : "Status report rejected: HTTP " + IntegerToString(status));
  }

//+------------------------------------------------------------------+
//| Panel                                                            |
//+------------------------------------------------------------------+
void PanelLine(const int idx, const string text, const color clr)
  {
   string name = "ASM_" + IntegerToString(idx);
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_RIGHT_UPPER);
      ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, InpPanelFontSize);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, false);
     }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, InpPanelX);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, InpPanelY + idx * (InpPanelFontSize + 6));
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

void UpdatePanel()
  {
   if(!InpShowPanel)
      return;
   int row = 0;

   if(g_masterMismatch)
      PanelLine(row++, "NEXAL Copier  ·  HOLDING (master changed)", clrOrangeRed);
   else if(g_halted)
      PanelLine(row++, "NEXAL Copier  ·  NO NEW COPIES (daily loss)", clrOrangeRed);
   else if(InpDryRun)
      PanelLine(row++, "NEXAL Copier  ·  DRY RUN", clrGold);
   else
      PanelLine(row++, "NEXAL Copier  ·  LIVE", clrLime);

   string conn;
   color  connClr = InpPanelColor;
   if(g_lastPollMs == 0)
     {
      conn = "master: connecting...";
      connClr = clrGold;
     }
   else
     {
      int age = (int)((GetTickCount64() - g_lastPollMs) / 1000);
      conn = "master " + g_masterLogin + "  ·  " + IntegerToString(age) + "s ago";
      if(!g_feedOk || age > InpPollSeconds * 3)
        {
         conn += "  (holding)";
         connClr = clrOrangeRed;
        }
     }
   PanelLine(row++, conn, connClr);

   int open = 0, pend = 0, skip = 0;
   for(int i = ArraySize(g_links) - 1; i >= 0; i--)
     {
      if(g_links[i].state == LS_OPEN) open++;
      else if(g_links[i].state == LS_PENDING) pend++;
      else if(g_links[i].state == LS_SKIPPED) skip++;
     }
   PanelLine(row++, StringFormat("copies: %d open · %d pending · %d skipped", open, pend, skip), InpPanelColor);
   PanelLine(row++, StringFormat("sync: %d ok · %d issue(s)", g_synced, g_issues), g_issues > 0 ? clrGold : clrLime);
   PanelLine(row++, "sizing: " + SizingLabel(), InpPanelColor);

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_dayStartEquity > 0.0)
     {
      double dayPnl = equity - g_dayStartEquity;
      PanelLine(row++, StringFormat("day: %+.2f (%+.2f%%)", dayPnl, dayPnl / g_dayStartEquity * 100.0),
                dayPnl >= 0.0 ? clrLime : clrOrangeRed);
     }
   PanelLine(row++, StringFormat("equity: %.2f", equity), InpPanelColor);

   PanelLine(row++, "── recent ──", InpPanelColor);
   for(int i = 0; i < g_logCount; i++)
      PanelLine(row++, g_logLines[i], g_logColors[i]);
   ChartRedraw(0);
  }

void RemovePanel()
  {
   ObjectsDeleteAll(0, "ASM_");
   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
