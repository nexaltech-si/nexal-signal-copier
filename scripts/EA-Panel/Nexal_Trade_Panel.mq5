//+------------------------------------------------------------------+
//|                                       Nexal_Trade_Panel.mq5     |
//|  v6.91                                                            |
//|   - NEW: Clickable scroll buttons (▲/▼) on HIST and LIVE tabs    |
//|   - NEW: Section headers show position counter "X-Y of Z"        |
//|   - NEW: Version footer label at bottom of every tab             |
//|   - InpHistoryRows default raised to 20, InpLiveRows to 10       |
//|   - All v6.90 features included (ACC tab, mouse wheel, etc.)     |
//+------------------------------------------------------------------+
#property copyright "Nexal Trade Panel"
#property version   "6.91"
#property strict

#include <Trade/Trade.mqh>

//--- General inputs
input string InpSymbol           = "";
input long   InpMagic            = -1;
input bool   InpOnlyImprove      = true;
input double InpLotSize          = 0.01;
input bool   InpDisableChartDrag = true;
input int    InpSlippagePoints   = 50;
input double InpComboBeOffset    = 0.50;  // $ offset for Close+BE combo
input int    InpHistoryRows      = 20;
input int    InpLiveRows         = 10;

input int    InpAnchorX          = 60;
input int    InpAnchorY          = 60;
input int    InpBtnW             = 74;   // max button width — panel auto-scales with chart width
input int    InpBtnH             = 20;   // base unit; price row = H×φ = 32
input int    InpGap              = 2;
input int    InpFramePad         = 4;
//-------------------------------------------------------------------

#define PFX "HsP_"
#define TAB_TRADING "trading"
#define TAB_HISTORY "history"
#define TAB_HELP    "help"
#define TAB_LIVE    "live"
#define TAB_ACC     "account"
#define TAB_ACCOUNT "account"
#define OFFSCREEN -10000
#define PRICE_H 32   // H × φ ≈ 32 — golden-ratio taller price row
#define HEADER_H 30  // header strip height

CTrade trade;
string g_chartSym;
string g_targetSym;

string g_currentTab = TAB_TRADING;

string g_activeMode = "";          // only trails are modes now
ulong  g_activeTickets[];
int    g_activeHistIdx = -1;

double g_bePerOffset = 0.50;       // $ offset for BE/Trade
double g_lotSize     = 0.01;

datetime g_lastBlink = 0;
bool     g_dotBright = true;

bool     g_symDropdownOpen = false;
string   g_dropdownNames[];

// Bulk symbol selector (LIVE tab) — independent of global target
string   g_bulkSym = "";
bool     g_bulkDropdownOpen = false;
string   g_bulkDropdownNames[];

int  g_panelX = 60;
int  g_panelY = 60;
bool g_isDragging   = false;
bool g_leftWasDown  = false;
int  g_dragGrabX    = 0;
int  g_dragGrabY    = 0;
int  g_lastMouseX   = 0;
int  g_lastMouseY   = 0;

// Scroll offsets for History and Live tabs
int  g_histScrollOffset = 0;
int  g_liveScrollOffset = 0;

// Collapsible section states (Trading tab)
bool g_collapsedTrade = false;
bool g_collapsedOrder = false;
bool g_collapsedMgm   = false;
bool g_collapsedClose = false;

struct PosInfo { ulong ticket; double entry; double volume; };

struct HistoryEntry
{
   datetime time;
   string   text;
   bool     active;
   string   modeKey;
};
HistoryEntry g_history[];

// Live trade row tickets (filled by UpdateLiveTrades)
ulong g_liveTickets[];
ulong g_liveTicketsCache[];   // previous tickets per row — to know when row changed

double TRAIL_FAST_START = 0.50, TRAIL_FAST_STEP = 2.0,  TRAIL_FAST_ADD = 1.0;
double TRAIL_MED_START  = 0.50, TRAIL_MED_STEP  = 4.0,  TRAIL_MED_ADD  = 2.0;
double TRAIL_SLOW_START = 0.50, TRAIL_SLOW_STEP = 10.0, TRAIL_SLOW_ADD = 8.0;

//--- Colors — Deep navy AI canvas, matches dashboard dark palette exactly
// Surface ladder: BG(#090d16) → HEADER → INFO_BG → ACTION → SECTION_HDR → TAB_ON
// Primary accent: #29ADFF (electric sky blue) — same as dashboard --primary
color COL_BG          = (color)C'9,13,22';     // #090d16 — dashboard html.dark bg
color COL_BORDER      = (color)C'29,36,52';    // #1d2434 — dashboard --border
color COL_HEADER      = (color)C'13,20,35';    // #0d1423 — card surface
color COL_TAB_OFF     = (color)C'20,28,48';    // #141c30 — inactive tab (secondary)
color COL_TAB_ON      = (color)C'41,173,255';  // #29ADFF — active tab filled electric blue
color COL_SECTION_HDR = (color)C'16,24,42';    // #10182a — section row (subtle lift)
color COL_LABEL       = (color)C'13,20,35';    // #0d1423 — label / empty-row bg
color COL_ACTION      = (color)C'24,34,58';    // #18223a — generic action buttons
color COL_INFO_BG     = (color)C'16,23,40';    // #101728 — data display bg
color COL_ACTIVE      = (color)C'41,173,255';  // #29ADFF — electric blue (dashboard primary)
color COL_DANGER      = (color)C'242,48,80';   // #F23050 — dashboard destructive
color COL_WARNING     = (color)C'251,166,32';  // #FBA620 — dashboard gold
color COL_BUY         = (color)C'36,200,122';  // #24C87A — dashboard success/emerald
color COL_SELL        = (color)C'242,48,80';   // #F23050 — dashboard destructive
color COL_PRICE_BUY   = (color)C'22,130,78';   // deep emerald — large BUY display
color COL_PRICE_SELL  = (color)C'160,30,52';   // deep rose — large SELL display
color COL_LOT         = (color)C'22,32,56';    // navy tint — lot ± adjuster buttons
color COL_LOT_DISP    = (color)C'32,46,80';    // lighter navy — lot display
color COL_BE_ADJ      = (color)C'22,32,56';    // navy tint — BE ± adjuster buttons
color COL_BE_DISP     = (color)C'32,46,80';    // lighter navy — BE display
color COL_BE_PRESET   = (color)C'24,62,128';   // deep electric blue — BE presets
color COL_BEPT        = (color)C'41,173,255';  // #29ADFF — BE/Trade primary CTA
color COL_TRAIL       = (color)C'18,50,100';   // deep navy-blue — trail modes
color COL_CLOSE       = (color)C'18,72,64';    // deep teal-navy — partial close
color COL_CLOSE_COMBO = (color)C'56,20,100';   // deep violet-navy — close+BE combo
color COL_CLOSE_BUY   = (color)C'36,200,122';  // #24C87A — emerald close buy
color COL_CLOSE_SELL  = (color)C'242,48,80';   // #F23050 — rose close sell
color COL_CLOSE_ALL   = (color)C'251,166,32';  // #FBA620 — gold close all
color COL_STATUS_DOT  = (color)C'41,173,255';  // #29ADFF — electric blue live dot
color COL_DOT_DIM     = (color)C'20,50,80';    // dim navy-blue — off-tick
color COL_TXT         = (color)C'224,234,248'; // #E0EAF8 — dashboard --foreground (blue-white)
color COL_TXT_MUTED   = (color)C'102,123,153'; // #667b99 — dashboard --muted-foreground
color COL_TXT_DARK    = (color)C'9,13,22';     // #090d16 — dark navy text (on bright bgs)
color COL_STOP_BTN    = (color)C'242,48,80';   // #F23050 — rose STOP button
color COL_STOP_OFF    = (color)C'24,34,58';    // dim navy off-state
color COL_PNL_POS     = (color)C'36,200,122';  // #24C87A — emerald P&L positive
color COL_PNL_NEG     = (color)C'242,48,80';   // #F23050 — rose P&L negative

// Effective button width — computed dynamically from chart width in RecalcBtnW()
int g_btnW = 74;

//+------------------------------------------------------------------+
//|  OBJECT HELPERS                                                   |
//+------------------------------------------------------------------+
void CreateRect(string name, color bg, color border)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_COLOR, border);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
}
void CreateButton(string name, string label, color bg, color txt, int fontSize=9, string font="Arial Bold")
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetString (0, name, OBJPROP_TEXT, label);
   ObjectSetInteger(0, name, OBJPROP_COLOR, txt);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, COL_BG);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontSize);
   ObjectSetString (0, name, OBJPROP_FONT, font);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
}
void Place(string name, int x, int y, int w, int h)
{
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
}
void HideObj(string name) { Place(name, OFFSCREEN, OFFSCREEN, 10, 10); }
void SetText(string name, string s) { ObjectSetString(0, name, OBJPROP_TEXT, s); }
void SetBG(string name, color c) { ObjectSetInteger(0, name, OBJPROP_BGCOLOR, c); }
void SetTC(string name, color c) { ObjectSetInteger(0, name, OBJPROP_COLOR, c); }
void CreateEdit(string name, color bg, color txt)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_EDIT, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetString (0, name, OBJPROP_TEXT, "");
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, txt);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, COL_BG);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
   ObjectSetString (0, name, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, name, OBJPROP_ALIGN, ALIGN_CENTER);
   ObjectSetInteger(0, name, OBJPROP_READONLY, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 10);
}

//+------------------------------------------------------------------+
//|  ALL-MODE HELPERS                                                 |
//+------------------------------------------------------------------+
bool   IsAllMode()        { return (g_targetSym == "ALL"); }
string EffectiveSymbol()  { return IsAllMode() ? g_chartSym : g_targetSym; }

//+------------------------------------------------------------------+
//|  DOLLAR -> PRICE OFFSET (account for tick value + lot size)       |
//+------------------------------------------------------------------+
double DollarToPriceOffset(string sym, double dollarOffset, double lotSize)
{
   double tickValue = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue <= 0.0 || tickSize <= 0.0 || lotSize <= 0.0)
      return dollarOffset;   // safe fallback
   return dollarOffset * tickSize / (tickValue * lotSize);
}

//+------------------------------------------------------------------+
//|  SYMBOL MANAGEMENT                                                |
//+------------------------------------------------------------------+
int CountMarketWatch() { return SymbolsTotal(true); }
int FindSymbolIndex(string sym)
{
   int total = CountMarketWatch();
   for(int i = 0; i < total; i++) if(SymbolName(i, true) == sym) return i;
   return -1;
}

//+------------------------------------------------------------------+
//|  HISTORY                                                          |
//+------------------------------------------------------------------+
int AddHistory(string text, bool active=false, string modeKey="")
{
   int n = ArraySize(g_history);
   ArrayResize(g_history, n + 1);
   g_history[n].time    = TimeCurrent();
   g_history[n].text    = text;
   g_history[n].active  = active;
   g_history[n].modeKey = modeKey;
   if(g_currentTab == TAB_HISTORY) RenderHistory();
   return n;
}
void MarkHistoryDone(int idx)
{
   if(idx < 0 || idx >= ArraySize(g_history)) return;
   g_history[idx].active  = false;
   g_history[idx].modeKey = "";
   if(g_currentTab == TAB_HISTORY) RenderHistory();
}

//+------------------------------------------------------------------+
//|  TICKET COLLECTION                                                |
//+------------------------------------------------------------------+
int CollectAllTickets(ulong &dest[])
{
   ArrayResize(dest, 0);
   bool all = IsAllMode();
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if(!all && PositionGetString(POSITION_SYMBOL) != g_targetSym) continue;
      if(InpMagic >= 0 && PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      int n = ArraySize(dest);
      ArrayResize(dest, n + 1);
      dest[n] = t;
   }
   return ArraySize(dest);
}
int CollectTickets(ulong &dest[], ENUM_POSITION_TYPE wt, bool any)
{
   ArrayResize(dest, 0);
   bool all = IsAllMode();
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if(!all && PositionGetString(POSITION_SYMBOL) != g_targetSym) continue;
      if(InpMagic >= 0 && PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(!any && (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != wt) continue;
      int n = ArraySize(dest); ArrayResize(dest, n+1); dest[n] = t;
   }
   return ArraySize(dest);
}
int CollectByProfit(ulong &dest[], bool wantProfit)
{
   ArrayResize(dest, 0);
   bool all = IsAllMode();
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if(!all && PositionGetString(POSITION_SYMBOL) != g_targetSym) continue;
      if(InpMagic >= 0 && PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      double p = PositionGetDouble(POSITION_PROFIT) +
                 PositionGetDouble(POSITION_SWAP) +
                 PositionGetDouble(POSITION_COMMISSION);
      bool isP = (p >= 0);
      if(wantProfit && !isP) continue;
      if(!wantProfit && isP) continue;
      int n = ArraySize(dest); ArrayResize(dest, n+1); dest[n] = t;
   }
   return ArraySize(dest);
}
void SnapshotActiveTickets() { CollectAllTickets(g_activeTickets); }
int CountLivingActiveTickets()
{
   int c = 0;
   for(int i = 0; i < ArraySize(g_activeTickets); i++)
      if(PositionSelectByTicket(g_activeTickets[i])) c++;
   return c;
}

//+------------------------------------------------------------------+
//|  TIMEFRAME HELPER                                                 |
//+------------------------------------------------------------------+
string TFString()
{
   ENUM_TIMEFRAMES tf = (ENUM_TIMEFRAMES)Period();
   switch(tf)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
      case PERIOD_MN1: return "MN1";
   }
   return EnumToString(tf);
}

//+------------------------------------------------------------------+
//|  PERSISTENCE                                                      |
//+------------------------------------------------------------------+
void SavePanelPos()  { GlobalVariableSet("HsP_X_"+g_chartSym, (double)g_panelX);
                       GlobalVariableSet("HsP_Y_"+g_chartSym, (double)g_panelY); }
void LoadPanelPos()
{
   if(GlobalVariableCheck("HsP_X_"+g_chartSym)) g_panelX = (int)GlobalVariableGet("HsP_X_"+g_chartSym);
   if(GlobalVariableCheck("HsP_Y_"+g_chartSym)) g_panelY = (int)GlobalVariableGet("HsP_Y_"+g_chartSym);
}
void SaveLot() { GlobalVariableSet("HsP_Lot_"+g_targetSym, g_lotSize); }
void LoadLot()
{
   if(GlobalVariableCheck("HsP_Lot_"+g_targetSym)) g_lotSize = GlobalVariableGet("HsP_Lot_"+g_targetSym);
   else g_lotSize = InpLotSize;
}
void SaveBePer() { GlobalVariableSet("HsP_BePer_"+g_targetSym, g_bePerOffset); }
void LoadBePer()
{
   if(GlobalVariableCheck("HsP_BePer_"+g_targetSym)) g_bePerOffset = GlobalVariableGet("HsP_BePer_"+g_targetSym);
   else g_bePerOffset = 0.50;
}
void SaveCollapseState()
{
   GlobalVariableSet("HsP_CollT_"+g_chartSym, g_collapsedTrade ? 1.0 : 0.0);
   GlobalVariableSet("HsP_CollO_"+g_chartSym, g_collapsedOrder ? 1.0 : 0.0);
   GlobalVariableSet("HsP_CollM_"+g_chartSym, g_collapsedMgm   ? 1.0 : 0.0);
   GlobalVariableSet("HsP_CollC_"+g_chartSym, g_collapsedClose ? 1.0 : 0.0);
}
void LoadCollapseState()
{
   if(GlobalVariableCheck("HsP_CollT_"+g_chartSym)) g_collapsedTrade = (GlobalVariableGet("HsP_CollT_"+g_chartSym) > 0.5);
   if(GlobalVariableCheck("HsP_CollO_"+g_chartSym)) g_collapsedOrder = (GlobalVariableGet("HsP_CollO_"+g_chartSym) > 0.5);
   if(GlobalVariableCheck("HsP_CollM_"+g_chartSym)) g_collapsedMgm   = (GlobalVariableGet("HsP_CollM_"+g_chartSym) > 0.5);
   if(GlobalVariableCheck("HsP_CollC_"+g_chartSym)) g_collapsedClose = (GlobalVariableGet("HsP_CollC_"+g_chartSym) > 0.5);
}

//+------------------------------------------------------------------+
int InnerW() { return 6 * g_btnW + 5 * InpGap; }
void RecalcBtnW()
{
   int chartW = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   if(chartW < 300) { g_btnW = InpBtnW; return; }
   // Target ~28% of chart width, clamped between 54 (minimum safe) and InpBtnW (user max)
   int target = (int)(chartW * 0.28);
   int w = (target - 5 * InpGap) / 6;
   g_btnW = MathMax(54, MathMin(InpBtnW, w));
}
int InnerH()
{
   int normalRows = 26;
   int extra      = PRICE_H - InpBtnH;
   return HEADER_H + normalRows * (InpBtnH + InpGap) + extra;
}
int FullW() { return InnerW() + 2 * InpFramePad; }
int FullH() { return InnerH() + 2 * InpFramePad; }

//+------------------------------------------------------------------+
//|  SYMBOL DROPDOWN                                                  |
//+------------------------------------------------------------------+
void CloseSymDropdown()
{
   if(!g_symDropdownOpen) return;
   for(int i = 0; i < ArraySize(g_dropdownNames); i++)
      if(ObjectFind(0, g_dropdownNames[i]) >= 0)
         ObjectDelete(0, g_dropdownNames[i]);
   ArrayResize(g_dropdownNames, 0);
   g_symDropdownOpen = false;
   ChartRedraw();
}
void CloseBulkDropdown()
{
   if(!g_bulkDropdownOpen) return;
   for(int i = 0; i < ArraySize(g_bulkDropdownNames); i++)
      if(ObjectFind(0, g_bulkDropdownNames[i]) >= 0)
         ObjectDelete(0, g_bulkDropdownNames[i]);
   ArrayResize(g_bulkDropdownNames, 0);
   g_bulkDropdownOpen = false;
   ChartRedraw();
}
void OpenBulkDropdown()
{
   CloseSymDropdown();
   CloseBulkDropdown();
   g_bulkDropdownOpen = true;

   int H = InpBtnH, pad = InpFramePad;
   int innerW = InnerW();
   int x0 = g_panelX + pad;

   int dispY = (int)ObjectGetInteger(0, PFX+"BULK_SYM_DISP", OBJPROP_YDISTANCE);
   int y     = dispY + H + 2;

   int total   = SymbolsTotal(true);
   int maxRows = MathMin(total, 15);
   ArrayResize(g_bulkDropdownNames, maxRows);

   for(int i = 0; i < maxRows; i++)
   {
      string symName = SymbolName(i, true);
      string objName = PFX + "BULK_DD_" + IntegerToString(i);
      color  bg      = (symName == g_bulkSym) ? COL_ACTIVE : COL_INFO_BG;
      CreateButton(objName, symName, bg, COL_TXT, 8, "Consolas");
      Place(objName, x0, y, innerW, H);
      ObjectSetInteger(0, objName, OBJPROP_BACK, false);
      ObjectSetInteger(0, objName, OBJPROP_ZORDER, 100);
      g_bulkDropdownNames[i] = objName;
      y += H + 1;
   }
   ChartRedraw();
}
void OpenSymDropdown()
{
   CloseSymDropdown();
   CloseBulkDropdown();
   g_symDropdownOpen = true;

   int W = InpBtnW, H = InpBtnH, gap = InpGap, pad = InpFramePad;
   int innerW = InnerW();
   int x0 = g_panelX + pad;

   // Anchor below INFO_TGT
   int tgtY = (int)ObjectGetInteger(0, PFX+"INFO_TGT", OBJPROP_YDISTANCE);
   int y    = tgtY + H + 2;

   int total   = SymbolsTotal(true);
   int maxRows = MathMin(total, 15) + 1;   // +1 for the ALL entry
   ArrayResize(g_dropdownNames, maxRows);

   //--- First entry: ALL
   {
      string objName = PFX + "DD_ALL";
      color  bg      = IsAllMode() ? COL_ACTIVE : COL_WARNING;
      CreateButton(objName, "ALL (every open trade)", bg, COL_TXT_DARK, 8);
      Place(objName, x0, y, innerW, H);
      ObjectSetInteger(0, objName, OBJPROP_BACK, false);
      ObjectSetInteger(0, objName, OBJPROP_ZORDER, 100);
      g_dropdownNames[0] = objName;
      y += H + 1;
   }
   //--- The actual symbols
   for(int i = 1; i < maxRows; i++)
   {
      int symIdx = i - 1;
      string symName = SymbolName(symIdx, true);
      string objName = PFX + "DD_" + IntegerToString(symIdx);
      color  bg      = (symName == g_targetSym) ? COL_ACTIVE : COL_INFO_BG;
      CreateButton(objName, symName, bg, COL_TXT, 8, "Consolas");
      Place(objName, x0, y, innerW, H);
      ObjectSetInteger(0, objName, OBJPROP_BACK, false);
      ObjectSetInteger(0, objName, OBJPROP_ZORDER, 100);
      g_dropdownNames[i] = objName;
      y += H + 1;
   }
   ChartRedraw();
}

//+------------------------------------------------------------------+
void CreateAll()
{
   CreateRect(PFX+"FRAME", COL_BG, COL_BORDER);

   //--- Header strip + tabs
   CreateRect  (PFX+"HEADER_BG", COL_HEADER, COL_HEADER);
   CreateButton(PFX+"TITLE",     "NEXAL", COL_HEADER, COL_TXT, 10);
   CreateButton(PFX+"DOT",       "●", COL_HEADER, COL_STATUS_DOT, 12);
   CreateButton(PFX+"TAB_TRD",   "TRADE", COL_TAB_ON,  COL_TXT_DARK, 8);
   CreateButton(PFX+"TAB_HIS",   "HIST",  COL_TAB_OFF, COL_TXT_MUTED, 8);
   CreateButton(PFX+"TAB_LIV",   "LIVE",  COL_TAB_OFF, COL_TXT_MUTED, 8);
   CreateButton(PFX+"TAB_ACC",   "ACC",   COL_TAB_OFF, COL_TXT_MUTED, 8);
   CreateButton(PFX+"TAB_HLP",   "HELP",  COL_TAB_OFF, COL_TXT_MUTED, 8);
   CreateButton(PFX+"DRAG",      ShortToString(0x2261), COL_HEADER, COL_TXT_MUTED, 9);

   //--- Info row (chart / timeframe / target)
   CreateButton(PFX+"INFO_CHART", "-", COL_LABEL, COL_TXT_MUTED, 8);
   CreateButton(PFX+"INFO_TF",    "-", COL_LABEL, COL_TXT_MUTED, 8);
   CreateButton(PFX+"INFO_TGT",   "-", COL_INFO_BG, COL_ACTIVE, 8);

   //--- Symbol row
   CreateButton(PFX+"SYM_LBL",   "SYM", COL_SECTION_HDR, COL_TXT_MUTED, 8);
   CreateButton(PFX+"SYM_DISP",  "-",   COL_INFO_BG, COL_TXT, 9, "Consolas");

   //--- LIVE PRICE section
   CreateButton(PFX+"SEC_TRD",    "LIVE PRICE", COL_SECTION_HDR, COL_ACTIVE, 9);
   CreateButton(PFX+"PRICE_BUY",  "BUY  -", COL_PRICE_BUY,  COL_TXT, 13, "Consolas");
   CreateButton(PFX+"PRICE_SELL", "SELL -", COL_PRICE_SELL, COL_TXT, 13, "Consolas");

   CreateButton(PFX+"LOT_MM",   "-.10", COL_LOT, COL_TXT_MUTED, 8);
   CreateButton(PFX+"LOT_M",    "-.01", COL_LOT, COL_TXT_MUTED, 8);
   CreateButton(PFX+"LOT_DISP", "0.01", COL_LOT_DISP, COL_TXT, 9, "Consolas");
   CreateButton(PFX+"LOT_P",    "+.01", COL_LOT, COL_TXT_MUTED, 8);
   CreateButton(PFX+"LOT_PP",   "+.10", COL_LOT, COL_TXT_MUTED, 8);

   //--- MARKET ORDER section
   CreateButton(PFX+"SEC_ORD",  "MARKET ORDER", COL_SECTION_HDR, COL_ACTIVE, 9);
   CreateButton(PFX+"MKT_BUY",  "BUY  0.01", COL_BUY,  COL_TXT, 9);
   CreateButton(PFX+"MKT_SELL", "SELL 0.01", COL_SELL, COL_TXT, 9);

   //--- BE & SECURE section
   CreateButton(PFX+"SEC_MGM",   "BE & SECURE", COL_SECTION_HDR, COL_ACTIVE, 9);
   CreateRect  (PFX+"SEP_MGM",   COL_BORDER, COL_BORDER);

   CreateButton(PFX+"BEALL_036",  "+0.36", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_050",  "+0.50", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_100",  "+1.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_200",  "+2.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_300",  "+3.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_400",  "+4.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_500",  "+5.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_600",  "+6.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_700",  "+7.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_800",  "+8.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_900",  "+9.00", COL_BE_PRESET, COL_TXT, 8, "Consolas");
   CreateButton(PFX+"BEALL_1000", "+10.0", COL_BE_PRESET, COL_TXT, 8, "Consolas");

   CreateButton(PFX+"BEPT_MM",   "-1.0", COL_BE_ADJ,  COL_TXT_MUTED, 8, "Consolas");
   CreateButton(PFX+"BEPT_M",    "-.50", COL_BE_ADJ,  COL_TXT_MUTED, 8, "Consolas");
   CreateButton(PFX+"BEPT_DISP", "0.50", COL_BE_DISP, COL_TXT, 9, "Consolas");
   CreateButton(PFX+"BEPT_P",    "+.50", COL_BE_ADJ,  COL_TXT_MUTED, 8, "Consolas");
   CreateButton(PFX+"BEPT_PP",   "+1.0", COL_BE_ADJ,  COL_TXT_MUTED, 8, "Consolas");
   CreateButton(PFX+"BEPT_GO",   "SET BE", COL_BEPT, COL_TXT_DARK, 8);

   CreateButton(PFX+"TRL_FAST",  "FAST",   COL_TRAIL, COL_TXT, 8);
   CreateButton(PFX+"TRL_MED",   "MED",    COL_TRAIL, COL_TXT, 8);
   CreateButton(PFX+"TRL_SLOW",  "SLOW",   COL_TRAIL, COL_TXT, 8);

   //--- CLOSE section
   CreateButton(PFX+"SEC_CLS",  "CLOSE OPTIONS", COL_SECTION_HDR, COL_ACTIVE, 9);
   CreateButton(PFX+"CLS_25",   "25%",     COL_CLOSE,      COL_TXT,      8);
   CreateButton(PFX+"CLS_50",   "50%",     COL_CLOSE,      COL_TXT,      8);
   CreateButton(PFX+"CLS_75",   "75%",     COL_CLOSE,      COL_TXT,      8);
   CreateButton(PFX+"CLS_BUY",  "BUY",     COL_CLOSE_BUY,  COL_TXT,      8);
   CreateButton(PFX+"CLS_SELL", "SELL",    COL_CLOSE_SELL, COL_TXT,      8);
   CreateButton(PFX+"CLS_ALL",  "ALL",     COL_CLOSE_ALL,  COL_TXT_DARK, 8);
   CreateButton(PFX+"CLS_PRF",  "PROFIT",  COL_BUY,        COL_TXT,      8);
   CreateButton(PFX+"CLS_LSS",  "LOSS",    COL_DANGER,     COL_TXT,      8);
   CreateButton(PFX+"CLS_50BE", "50%+BE",  COL_CLOSE_COMBO, COL_TXT,     8);
   CreateButton(PFX+"CLS_75BE", "75%+BE",  COL_CLOSE_COMBO, COL_TXT,     8);
   CreateButton(PFX+"CLS_80BE", "80%+BE",  COL_CLOSE_COMBO, COL_TXT,     8);

   //--- STATUS bar
   CreateButton(PFX+"SEC_STA", "STATUS",         COL_SECTION_HDR, COL_ACTIVE,    8);
   CreateButton(PFX+"STATUS",  "Nothing active", COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"STOP",    "STOP",           COL_STOP_OFF,    COL_TXT,       8);

   //--- HISTORY rows
   CreateButton(PFX+"HIS_HDR",  "HISTORY", COL_SECTION_HDR, COL_ACTIVE, 8);
   CreateButton(PFX+"HIS_UP",   ShortToString(0x25B2), COL_TAB_ON, COL_TXT_DARK, 8);  // ▲
   CreateButton(PFX+"HIS_DN",   ShortToString(0x25BC), COL_TAB_ON, COL_TXT_DARK, 8);  // ▼
   for(int i = 0; i < InpHistoryRows; i++)
   {
      CreateButton(PFX+"HIS_T_"+IntegerToString(i), "", COL_LABEL, COL_TXT_MUTED, 8);
      CreateButton(PFX+"HIS_A_"+IntegerToString(i), "", COL_LABEL, COL_TXT,       8, "Consolas");
      CreateButton(PFX+"HIS_S_"+IntegerToString(i), "", COL_LABEL, COL_TXT_MUTED, 8, "Consolas");
      CreateButton(PFX+"HIS_X_"+IntegerToString(i), "STOP", COL_STOP_OFF, COL_TXT, 8);
   }

   //--- HELP rows
   string helpT[] = {
      "Tabs MGM/HIST/HELP/LIVE",
      "Target / Chart / TF row",
      "Market Watch",
      "BUY / SELL prices",
      "Lot adjuster",
      "Market BUY / SELL",
      "BE 0.36 ... BE 10$",
      "BE/Trade",
      "Trail Fast",
      "Trail Medium",
      "Trail Slow",
      "Close 25 / 50 / 75%",
      "Close BUY / SELL / ALL",
      "Close Profits",
      "Close Loss",
      "50% + BE",
      "75% + BE",
      "80% + BE",
      "STOP",
      "LIVE per-trade"
   };
   string helpD[] = {
      "Switch panel views (Trading / History / Help / Live trades)",
      "Status info: current Target symbol, chart symbol, timeframe",
      "Click to open dropdown — change target symbol",
      "Live BUY/SELL prices (Ask / Bid) of target symbol",
      "Step buttons set lot size (-0.10 / -0.01 / +0.01 / +0.10)",
      "Open immediate market order at current Lot size",
      "ONE-SHOT: set SL on all trades for $ profit (worst entry)",
      "ONE-SHOT: set SL per trade at own entry + $ profit",
      "Persistent mode: start 0.50, every 2$ profit adds +1$",
      "Persistent mode: start 0.50, every 4$ profit adds +2$",
      "Persistent mode: start 0.50, every 10$ profit adds +8$",
      "Partial close, takes from worst-entry first",
      "Full close of selected position type",
      "Close all trades currently in profit",
      "Close all trades currently in loss",
      "Close 50% + immediately BE-lock the rest",
      "Close 75% + immediately BE-lock the rest",
      "Close 80% + immediately BE-lock the rest",
      "Stop the active TRAIL mode",
      "Edit SL/TP and click Set to apply per trade"
   };
   for(int i = 0; i < ArraySize(helpT); i++)
   {
      CreateButton(PFX+"HLP_T_"+IntegerToString(i), helpT[i], COL_SECTION_HDR, COL_TXT,       9);
      CreateButton(PFX+"HLP_D_"+IntegerToString(i), helpD[i], COL_LABEL,       COL_TXT_MUTED, 9);
   }

   //--- LIVE TRADES rows
   CreateButton(PFX+"LIV_HDR",       "LIVE TRADES", COL_SECTION_HDR, COL_ACTIVE, 8);
   CreateButton(PFX+"LIV_UP",        ShortToString(0x25B2), COL_TAB_ON, COL_TXT_DARK, 8);  // ▲
   CreateButton(PFX+"LIV_DN",        ShortToString(0x25BC), COL_TAB_ON, COL_TXT_DARK, 8);  // ▼
   CreateButton(PFX+"BULK_HDR",      "BULK:", COL_INFO_BG,    COL_TXT_MUTED, 8);
   CreateButton(PFX+"BULK_SYM_DISP", "-",     COL_INFO_BG,    COL_TXT,       9, "Consolas");
   CreateButton(PFX+"BULK_SLL",      "SL",    COL_LABEL,      COL_TXT_MUTED, 8);
   CreateButton(PFX+"BULK_TPL",      "TP",    COL_LABEL,      COL_TXT_MUTED, 8);
   CreateEdit  (PFX+"BULK_SLE",      COL_INFO_BG, COL_TXT);
   CreateEdit  (PFX+"BULK_TPE",      COL_INFO_BG, COL_TXT);
   CreateButton(PFX+"BULK_S",        "SET ALL", COL_WARNING, COL_TXT_DARK, 8);
   CreateRect  (PFX+"BULK_DIV",      COL_BORDER,  COL_BORDER);

   for(int i = 0; i < InpLiveRows; i++)
   {
      CreateButton(PFX+"LIV_INFO_"+IntegerToString(i), "",      COL_LABEL,  COL_TXT,       8, "Consolas");
      CreateButton(PFX+"LIV_C_"+IntegerToString(i),    "CLS",   COL_DANGER, COL_TXT,       8);
      CreateButton(PFX+"LIV_H_"+IntegerToString(i),    "50%",   COL_CLOSE,  COL_TXT,       8);
      CreateButton(PFX+"LIV_B_"+IntegerToString(i),    "BE",    COL_ACTION, COL_TXT,       8);
      CreateButton(PFX+"LIV_SLL_"+IntegerToString(i),  "SL",    COL_LABEL,  COL_TXT_MUTED, 8);
      CreateButton(PFX+"LIV_TPL_"+IntegerToString(i),  "TP",    COL_LABEL,  COL_TXT_MUTED, 8);
      CreateEdit  (PFX+"LIV_SLE_"+IntegerToString(i),  COL_INFO_BG, COL_TXT);
      CreateEdit  (PFX+"LIV_TPE_"+IntegerToString(i),  COL_INFO_BG, COL_TXT);
      CreateButton(PFX+"LIV_S_"+IntegerToString(i),    "SET",   COL_ACTION, COL_TXT,       8);
   }

   //--- ACCOUNT INFO tab
   CreateButton(PFX+"ACC_SEC1",  "ACCOUNT",      COL_SECTION_HDR, COL_ACTIVE,    8);
   CreateButton(PFX+"ACC_BAL_L", "Balance",      COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_BAL_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_EQU_L", "Equity",       COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_EQU_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_FRE_L", "Free Margin",  COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_FRE_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_MAR_L", "Used Margin",  COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_MAR_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_LEV_L", "Leverage",     COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_LEV_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_SEC2",  "P / L",        COL_SECTION_HDR, COL_ACTIVE,    8);
   CreateButton(PFX+"ACC_OPN_L", "Open",         COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_OPN_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_DAY_L", "Today",        COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_DAY_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_WEK_L", "Week",         COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_WEK_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_MTH_L", "Month",        COL_LABEL,       COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_MTH_V", "-",            COL_INFO_BG,     COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_YR_L",  "Year",     COL_LABEL,   COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_YR_V",  "-",       COL_INFO_BG, COL_TXT,       8, "Consolas");
   CreateButton(PFX+"ACC_ALL_L", "All time", COL_LABEL,  COL_TXT_MUTED, 8);
   CreateButton(PFX+"ACC_ALL_V", "-",        COL_INFO_BG, COL_TXT,      8, "Consolas");

   //--- Version footer (shown at bottom of every tab)
   CreateButton(PFX+"FOOTER_VER", "Nexal Trade Panel v6.91",
                COL_HEADER, COL_TXT_MUTED, 8);
}

//+------------------------------------------------------------------+
//|  HEADER (4 tabs) — shared placement                               |
//+------------------------------------------------------------------+
void PlaceHeader(int x0, int y, int innerW)
{
   // Header strip — HEADER_H=30, tabs 20px tall centered at y+5
   // Drag 16px | 5 tabs 38px each, 3px gap | title+dot on left
   Place(PFX+"HEADER_BG", x0, y, innerW, HEADER_H);
   Place(PFX+"TITLE",  x0+6,  y+5, 72, 20);
   Place(PFX+"DOT",    x0+80, y+5, 14, 20);
   int tY = y+5, tH = 20, tW = 38, tG = 3;
   Place(PFX+"DRAG",    x0+innerW-16,              tY, 16, tH);
   Place(PFX+"TAB_HLP", x0+innerW-16-tG-tW,        tY, tW, tH);
   Place(PFX+"TAB_ACC", x0+innerW-16-tG-2*(tW+tG), tY, tW, tH);
   Place(PFX+"TAB_LIV", x0+innerW-16-tG-3*(tW+tG), tY, tW, tH);
   Place(PFX+"TAB_HIS", x0+innerW-16-tG-4*(tW+tG), tY, tW, tH);
   Place(PFX+"TAB_TRD", x0+innerW-16-tG-5*(tW+tG), tY, tW, tH);
}
void PlaceInfoRow(int x0, int &y, int innerW)
{
   int H=InpBtnH, gap=InpGap;
   int thirdW = (innerW - 2*gap) / 3;
   Place(PFX+"INFO_TGT",   x0,                    y, thirdW, H);
   Place(PFX+"INFO_CHART", x0 + thirdW + gap,     y, thirdW, H);
   Place(PFX+"INFO_TF",    x0 + 2*(thirdW + gap), y, thirdW, H);
   y += H + gap;
}

//+------------------------------------------------------------------+
//|  LAYOUT — TRADING                                                 |
//+------------------------------------------------------------------+
void HideTradeSection()
{
   HideObj(PFX+"PRICE_BUY"); HideObj(PFX+"PRICE_SELL");
}
void HideOrderSection()
{
   HideObj(PFX+"LOT_MM");   HideObj(PFX+"LOT_M");
   HideObj(PFX+"LOT_DISP"); HideObj(PFX+"LOT_P"); HideObj(PFX+"LOT_PP");
   HideObj(PFX+"MKT_BUY");  HideObj(PFX+"MKT_SELL");
}
void HideMgmSection()
{
   HideObj(PFX+"SEP_MGM");
   HideObj(PFX+"BEALL_036"); HideObj(PFX+"BEALL_050"); HideObj(PFX+"BEALL_100");
   HideObj(PFX+"BEALL_200"); HideObj(PFX+"BEALL_300"); HideObj(PFX+"BEALL_400");
   HideObj(PFX+"BEALL_500"); HideObj(PFX+"BEALL_600"); HideObj(PFX+"BEALL_700");
   HideObj(PFX+"BEALL_800"); HideObj(PFX+"BEALL_900"); HideObj(PFX+"BEALL_1000");
   HideObj(PFX+"BEPT_MM"); HideObj(PFX+"BEPT_M"); HideObj(PFX+"BEPT_DISP");
   HideObj(PFX+"BEPT_P");  HideObj(PFX+"BEPT_PP"); HideObj(PFX+"BEPT_GO");
   HideObj(PFX+"TRL_FAST"); HideObj(PFX+"TRL_MED"); HideObj(PFX+"TRL_SLOW");
}
void HideCloseSection()
{
   HideObj(PFX+"CLS_25"); HideObj(PFX+"CLS_50"); HideObj(PFX+"CLS_75");
   HideObj(PFX+"CLS_BUY"); HideObj(PFX+"CLS_SELL"); HideObj(PFX+"CLS_ALL");
   HideObj(PFX+"CLS_PRF"); HideObj(PFX+"CLS_LSS");
   HideObj(PFX+"CLS_50BE"); HideObj(PFX+"CLS_75BE"); HideObj(PFX+"CLS_80BE");
}

void LayoutTrading()
{
   int W=g_btnW, H=InpBtnH, gap=InpGap, pad=InpFramePad;
   int rH = H + gap;
   int wide2 = 2*W + gap;
   int wide3 = 3*W + 2*gap;
   int innerW = InnerW();

   int x0 = g_panelX + pad;
   int y  = g_panelY + pad;

   PlaceHeader(x0, y, innerW);
   y += HEADER_H + gap;
   PlaceInfoRow(x0, y, innerW);

   HideAccount();
   HideObj(PFX+"HIS_HDR"); HideObj(PFX+"HIS_UP"); HideObj(PFX+"HIS_DN");
   HideObj(PFX+"LIV_HDR"); HideObj(PFX+"LIV_UP"); HideObj(PFX+"LIV_DN");

   //--- Symbol row
   Place(PFX+"SYM_LBL",  x0,         y, W,            H);
   Place(PFX+"SYM_DISP", x0+W+gap,   y, innerW-W-gap, H);
   y += rH;

   //--- Section: TRADE
   SetText(PFX+"SEC_TRD", (g_collapsedTrade ? "▶ LIVE PRICE" : "▼ LIVE PRICE"));
   Place(PFX+"SEC_TRD", x0, y, innerW, H); y += rH;
   if(!g_collapsedTrade)
   {
      Place(PFX+"PRICE_BUY",  x0,            y, wide3, PRICE_H);
      Place(PFX+"PRICE_SELL", x0+wide3+gap,  y, wide3, PRICE_H);
      y += PRICE_H + gap;
   }
   else HideTradeSection();

   //--- Section: MARKET ORDER (BUY/SELL first, then Lot adjuster)
   SetText(PFX+"SEC_ORD", (g_collapsedOrder ? "▶ MARKET ORDER" : "▼ MARKET ORDER"));
   Place(PFX+"SEC_ORD", x0, y, innerW, H); y += rH;
   if(!g_collapsedOrder)
   {
      Place(PFX+"MKT_BUY",  x0,           y, wide3, H);
      Place(PFX+"MKT_SELL", x0+wide3+gap, y, wide3, H);
      y += rH;
      Place(PFX+"LOT_MM",   x0 + 0*(W+gap), y, W, H);
      Place(PFX+"LOT_M",    x0 + 1*(W+gap), y, W, H);
      Place(PFX+"LOT_DISP", x0 + 2*(W+gap), y, wide2, H);
      Place(PFX+"LOT_P",    x0 + 4*(W+gap), y, W, H);
      Place(PFX+"LOT_PP",   x0 + 5*(W+gap), y, W, H);
      y += rH;
   }
   else HideOrderSection();

   //--- Section: TRADE MANAGEMENT (BE & SECURE)
   SetText(PFX+"SEC_MGM", (g_collapsedMgm ? "▶ BE & SECURE" : "▼ BE & SECURE"));
   Place(PFX+"SEC_MGM", x0, y, innerW, H); y += rH;
   if(!g_collapsedMgm)
   {
      // Subtle separator line under header
      Place(PFX+"SEP_MGM", x0, y-gap+1, innerW, 2);
      // BE row 1
      Place(PFX+"BEALL_036", x0+0*(W+gap), y, W, H);
      Place(PFX+"BEALL_050", x0+1*(W+gap), y, W, H);
      Place(PFX+"BEALL_100", x0+2*(W+gap), y, W, H);
      Place(PFX+"BEALL_200", x0+3*(W+gap), y, W, H);
      Place(PFX+"BEALL_300", x0+4*(W+gap), y, W, H);
      Place(PFX+"BEALL_400", x0+5*(W+gap), y, W, H);
      y += rH;
      // BE row 2
      Place(PFX+"BEALL_500",  x0+0*(W+gap), y, W, H);
      Place(PFX+"BEALL_600",  x0+1*(W+gap), y, W, H);
      Place(PFX+"BEALL_700",  x0+2*(W+gap), y, W, H);
      Place(PFX+"BEALL_800",  x0+3*(W+gap), y, W, H);
      Place(PFX+"BEALL_900",  x0+4*(W+gap), y, W, H);
      Place(PFX+"BEALL_1000", x0+5*(W+gap), y, W, H);
      y += rH;
      // BE/Trade adjuster row
      Place(PFX+"BEPT_MM",   x0+0*(W+gap), y, W, H);
      Place(PFX+"BEPT_M",    x0+1*(W+gap), y, W, H);
      Place(PFX+"BEPT_DISP", x0+2*(W+gap), y, W, H);
      Place(PFX+"BEPT_P",    x0+3*(W+gap), y, W, H);
      Place(PFX+"BEPT_PP",   x0+4*(W+gap), y, W, H);
      Place(PFX+"BEPT_GO",   x0+5*(W+gap), y, W, H);
      y += rH;
      // Trail row
      Place(PFX+"TRL_FAST", x0,           y, wide2, H);
      Place(PFX+"TRL_MED",  x0+2*(W+gap), y, wide2, H);
      Place(PFX+"TRL_SLOW", x0+4*(W+gap), y, wide2, H);
      y += rH;
   }
   else HideMgmSection();

   //--- Section: CLOSE MANAGEMENT
   SetText(PFX+"SEC_CLS", (g_collapsedClose ? "▶ CLOSE OPTIONS" : "▼ CLOSE OPTIONS"));
   Place(PFX+"SEC_CLS", x0, y, innerW, H); y += rH;
   if(!g_collapsedClose)
   {
      Place(PFX+"CLS_25",   x0,             y, wide2, H);
      Place(PFX+"CLS_50",   x0+2*(W+gap),   y, wide2, H);
      Place(PFX+"CLS_75",   x0+4*(W+gap),   y, wide2, H);
      y += rH;
      Place(PFX+"CLS_BUY",  x0,             y, wide2, H);
      Place(PFX+"CLS_SELL", x0+2*(W+gap),   y, wide2, H);
      Place(PFX+"CLS_ALL",  x0+4*(W+gap),   y, wide2, H);
      y += rH;
      Place(PFX+"CLS_PRF",  x0,             y, wide3, H);
      Place(PFX+"CLS_LSS",  x0+wide3+gap,   y, wide3, H);
      y += rH;
      Place(PFX+"CLS_50BE", x0,             y, wide2, H);
      Place(PFX+"CLS_75BE", x0+2*(W+gap),   y, wide2, H);
      Place(PFX+"CLS_80BE", x0+4*(W+gap),   y, wide2, H);
      y += rH;
   }
   else HideCloseSection();

   //--- STATUS (always visible)
   Place(PFX+"SEC_STA", x0, y, innerW, H); y += rH;
   Place(PFX+"STATUS",  x0,           y, 4*W + 3*gap, H);
   Place(PFX+"STOP",    x0+4*(W+gap), y, wide2, H);
   y += rH;

   //--- Resize FRAME to actual content
   Place(PFX+"FOOTER_VER", g_panelX + InpFramePad, y, InnerW(), 16);
   y += 16;
   int totalH = (y - g_panelY) - gap + pad;
   Place(PFX+"FRAME", g_panelX, g_panelY, FullW(), totalH);

   //--- Hide other tabs' content
   for(int i = 0; i < InpHistoryRows; i++)
   {
      HideObj(PFX+"HIS_T_"+IntegerToString(i));
      HideObj(PFX+"HIS_A_"+IntegerToString(i));
      HideObj(PFX+"HIS_S_"+IntegerToString(i));
      HideObj(PFX+"HIS_X_"+IntegerToString(i));
   }
   for(int i = 0; i < 20; i++)
   {
      HideObj(PFX+"HLP_T_"+IntegerToString(i));
      HideObj(PFX+"HLP_D_"+IntegerToString(i));
   }
   for(int i = 0; i < InpLiveRows; i++)
   {
      HideObj(PFX+"LIV_INFO_"+IntegerToString(i));
      HideObj(PFX+"LIV_C_"+IntegerToString(i));
      HideObj(PFX+"LIV_H_"+IntegerToString(i));
      HideObj(PFX+"LIV_B_"+IntegerToString(i));
      HideObj(PFX+"LIV_SLE_"+IntegerToString(i));
      HideObj(PFX+"LIV_TPE_"+IntegerToString(i));
      HideObj(PFX+"LIV_S_"+IntegerToString(i));
      HideObj(PFX+"LIV_SLL_"+IntegerToString(i));
      HideObj(PFX+"LIV_TPL_"+IntegerToString(i));
   }
   HideObj(PFX+"BULK_HDR"); HideObj(PFX+"BULK_SLL"); HideObj(PFX+"BULK_TPL");
   HideObj(PFX+"BULK_SLE"); HideObj(PFX+"BULK_TPE"); HideObj(PFX+"BULK_S");
   HideObj(PFX+"BULK_SYM_DISP"); HideObj(PFX+"BULK_DIV");
   ChartRedraw();
}

//+------------------------------------------------------------------+
void HideTradingObjects()
{
   string keys[] = {
      "SYM_LBL","SYM_DISP",
      "SEC_TRD","PRICE_BUY","PRICE_SELL",
      "LOT_MM","LOT_M","LOT_DISP","LOT_P","LOT_PP",
      "SEC_ORD","MKT_BUY","MKT_SELL",
      "SEC_MGM","SEP_MGM",
      "BEALL_036","BEALL_050","BEALL_100","BEALL_200","BEALL_300","BEALL_400",
      "BEALL_500","BEALL_600","BEALL_700","BEALL_800","BEALL_900","BEALL_1000",
      "BEPT_MM","BEPT_M","BEPT_DISP","BEPT_P","BEPT_PP","BEPT_GO",
      "TRL_FAST","TRL_MED","TRL_SLOW",
      "SEC_CLS","CLS_25","CLS_50","CLS_75",
      "CLS_BUY","CLS_SELL","CLS_ALL",
      "CLS_PRF","CLS_LSS",
      "CLS_50BE","CLS_75BE","CLS_80BE",
      "SEC_STA","STATUS","STOP"
   };
   for(int i = 0; i < ArraySize(keys); i++) HideObj(PFX+keys[i]);
}

//+------------------------------------------------------------------+
void LayoutHistory()
{
   int W=g_btnW, H=InpBtnH, gap=InpGap, pad=InpFramePad;
   int rH = H + gap;
   int innerW = InnerW();

   int x0 = g_panelX + pad;
   int y  = g_panelY + pad;

   PlaceHeader(x0, y, innerW);
   y += HEADER_H + gap;
   PlaceInfoRow(x0, y, innerW);

   HideTradingObjects();
   HideAccount();
   HideObj(PFX+"HIS_HDR"); HideObj(PFX+"HIS_UP"); HideObj(PFX+"HIS_DN");
   HideObj(PFX+"LIV_HDR"); HideObj(PFX+"LIV_UP"); HideObj(PFX+"LIV_DN");
   for(int i = 0; i < 20; i++)
   {
      HideObj(PFX+"HLP_T_"+IntegerToString(i));
      HideObj(PFX+"HLP_D_"+IntegerToString(i));
   }
   for(int i = 0; i < InpLiveRows; i++)
   {
      HideObj(PFX+"LIV_INFO_"+IntegerToString(i));
      HideObj(PFX+"LIV_C_"+IntegerToString(i));
      HideObj(PFX+"LIV_H_"+IntegerToString(i));
      HideObj(PFX+"LIV_B_"+IntegerToString(i));
      HideObj(PFX+"LIV_SLE_"+IntegerToString(i));
      HideObj(PFX+"LIV_TPE_"+IntegerToString(i));
      HideObj(PFX+"LIV_S_"+IntegerToString(i));
      HideObj(PFX+"LIV_SLL_"+IntegerToString(i));
      HideObj(PFX+"LIV_TPL_"+IntegerToString(i));
   }
   HideObj(PFX+"BULK_HDR"); HideObj(PFX+"BULK_SLL"); HideObj(PFX+"BULK_TPL");
   HideObj(PFX+"BULK_SLE"); HideObj(PFX+"BULK_TPE"); HideObj(PFX+"BULK_S");
   HideObj(PFX+"BULK_SYM_DISP"); HideObj(PFX+"BULK_DIV");

   HideObj(PFX+"BULK_HDR"); HideObj(PFX+"BULK_SLL"); HideObj(PFX+"BULK_TPL");
   HideObj(PFX+"BULK_SLE"); HideObj(PFX+"BULK_TPE"); HideObj(PFX+"BULK_S");
   HideObj(PFX+"BULK_SYM_DISP"); HideObj(PFX+"BULK_DIV");
   HideObj(PFX+"LIV_HDR"); HideObj(PFX+"LIV_UP"); HideObj(PFX+"LIV_DN");

   //--- History section header with scroll buttons (right-aligned)
   int btnSz = 22;
   int hdrW  = innerW - 2*(btnSz + gap);
   Place(PFX+"HIS_HDR", x0,                              y, hdrW,  H);
   Place(PFX+"HIS_UP",  x0 + hdrW + gap,                 y, btnSz, H);
   Place(PFX+"HIS_DN",  x0 + hdrW + btnSz + 2*gap,       y, btnSz, H);
   y += rH;

   int tW = (int)(0.18 * innerW);
   int aW = (int)(0.48 * innerW);
   int sW = (int)(0.20 * innerW);
   int xW = innerW - tW - aW - sW - 3*gap;

   for(int i = 0; i < InpHistoryRows; i++)
   {
      Place(PFX+"HIS_T_"+IntegerToString(i), x0,                y, tW, H);
      Place(PFX+"HIS_A_"+IntegerToString(i), x0+tW+gap,         y, aW, H);
      Place(PFX+"HIS_S_"+IntegerToString(i), x0+tW+aW+2*gap,    y, sW, H);
      Place(PFX+"HIS_X_"+IntegerToString(i), x0+tW+aW+sW+3*gap, y, xW, H);
      y += rH;
   }
   Place(PFX+"FOOTER_VER", g_panelX + InpFramePad, y, InnerW(), 16);
   y += 16;
   int totalH = (y - g_panelY) - gap + pad;
   Place(PFX+"FRAME", g_panelX, g_panelY, FullW(), totalH);
   RenderHistory();
   ChartRedraw();
}

//+------------------------------------------------------------------+
void LayoutHelp()
{
   int W=g_btnW, H=InpBtnH, gap=InpGap, pad=InpFramePad;
   int rH = H + gap;
   int innerW = InnerW();

   int x0 = g_panelX + pad;
   int y  = g_panelY + pad;

   PlaceHeader(x0, y, innerW);
   y += HEADER_H + gap;
   PlaceInfoRow(x0, y, innerW);

   HideTradingObjects();
   HideAccount();
   HideObj(PFX+"HIS_HDR"); HideObj(PFX+"HIS_UP"); HideObj(PFX+"HIS_DN");
   HideObj(PFX+"LIV_HDR"); HideObj(PFX+"LIV_UP"); HideObj(PFX+"LIV_DN");
   for(int i = 0; i < InpHistoryRows; i++)
   {
      HideObj(PFX+"HIS_T_"+IntegerToString(i));
      HideObj(PFX+"HIS_A_"+IntegerToString(i));
      HideObj(PFX+"HIS_S_"+IntegerToString(i));
      HideObj(PFX+"HIS_X_"+IntegerToString(i));
   }
   for(int i = 0; i < InpLiveRows; i++)
   {
      HideObj(PFX+"LIV_INFO_"+IntegerToString(i));
      HideObj(PFX+"LIV_C_"+IntegerToString(i));
      HideObj(PFX+"LIV_H_"+IntegerToString(i));
      HideObj(PFX+"LIV_B_"+IntegerToString(i));
      HideObj(PFX+"LIV_SLE_"+IntegerToString(i));
      HideObj(PFX+"LIV_TPE_"+IntegerToString(i));
      HideObj(PFX+"LIV_S_"+IntegerToString(i));
      HideObj(PFX+"LIV_SLL_"+IntegerToString(i));
      HideObj(PFX+"LIV_TPL_"+IntegerToString(i));
   }
   HideObj(PFX+"BULK_HDR"); HideObj(PFX+"BULK_SLL"); HideObj(PFX+"BULK_TPL");
   HideObj(PFX+"BULK_SLE"); HideObj(PFX+"BULK_TPE"); HideObj(PFX+"BULK_S");
   HideObj(PFX+"BULK_SYM_DISP"); HideObj(PFX+"BULK_DIV");

   int nameW = 2*W + gap;
   int descW = innerW - nameW - gap;
   for(int i = 0; i < 20; i++)
   {
      Place(PFX+"HLP_T_"+IntegerToString(i), x0,           y, nameW, H);
      Place(PFX+"HLP_D_"+IntegerToString(i), x0+nameW+gap, y, descW, H);
      y += rH;
   }
   Place(PFX+"FOOTER_VER", g_panelX + InpFramePad, y, InnerW(), 16);
   y += 16;
   int totalH = (y - g_panelY) - gap + pad;
   Place(PFX+"FRAME", g_panelX, g_panelY, FullW(), totalH);
   ChartRedraw();
}

//+------------------------------------------------------------------+
void LayoutLive()
{
   int W=g_btnW, H=InpBtnH, gap=InpGap, pad=InpFramePad;
   int rH = H + gap;
   int innerW = InnerW();

   int x0 = g_panelX + pad;
   int y  = g_panelY + pad;

   PlaceHeader(x0, y, innerW);
   y += HEADER_H + gap;
   PlaceInfoRow(x0, y, innerW);

   HideTradingObjects();
   HideAccount();
   HideObj(PFX+"HIS_HDR"); HideObj(PFX+"HIS_UP"); HideObj(PFX+"HIS_DN");
   HideObj(PFX+"LIV_HDR"); HideObj(PFX+"LIV_UP"); HideObj(PFX+"LIV_DN");
   for(int i = 0; i < InpHistoryRows; i++)
   {
      HideObj(PFX+"HIS_T_"+IntegerToString(i));
      HideObj(PFX+"HIS_A_"+IntegerToString(i));
      HideObj(PFX+"HIS_S_"+IntegerToString(i));
      HideObj(PFX+"HIS_X_"+IntegerToString(i));
   }
   for(int i = 0; i < 20; i++)
   {
      HideObj(PFX+"HLP_T_"+IntegerToString(i));
      HideObj(PFX+"HLP_D_"+IntegerToString(i));
   }
   HideObj(PFX+"HIS_HDR"); HideObj(PFX+"HIS_UP"); HideObj(PFX+"HIS_DN");

   // Section header with scroll buttons (right-aligned)
   int btnSz = 22;
   int hdrW  = innerW - 2*(btnSz + gap);
   Place(PFX+"LIV_HDR", x0,                              y, hdrW,  H);
   Place(PFX+"LIV_UP",  x0 + hdrW + gap,                 y, btnSz, H);
   Place(PFX+"LIV_DN",  x0 + hdrW + btnSz + 2*gap,       y, btnSz, H);
   HideObj(PFX+"SEC_TRD");
   y += rH;

   int wide2 = 2*W + gap;       // 154 px (2 cells)
   int wide4 = 4*W + 3*gap;     // 312 px (4 cells)
   int lblW  = 28;              // small SL/TP label
   int editW = wide2 - lblW - gap;  // SL/TP edit fields shrink to make room for labels

   //--- BULK SET section (independent symbol selector)
   {
      // Row 1: label + bulk symbol picker
      Place(PFX+"BULK_HDR",      x0,                y, 2*W + gap, H);
      Place(PFX+"BULK_SYM_DISP", x0+2*W+2*gap,      y, innerW - 2*W - 2*gap, H);
      SetText(PFX+"BULK_SYM_DISP", g_bulkSym);
      y += rH;

      // Row 2: SL/TP edit + Set All
      Place(PFX+"BULK_SLL", x0,                            y, lblW,  H);
      Place(PFX+"BULK_SLE", x0+lblW+gap,                   y, editW, H);
      Place(PFX+"BULK_TPL", x0+lblW+editW+2*gap,           y, lblW,  H);
      Place(PFX+"BULK_TPE", x0+2*lblW+editW+3*gap,         y, editW, H);
      Place(PFX+"BULK_S",   x0+2*lblW+2*editW+4*gap,       y, 2*W+gap, H);
      y += rH;

      // Visual divider line between bulk section and individual trade rows
      Place(PFX+"BULK_DIV", x0, y, innerW, 2);
      y += 6 + gap;  // bigger gap for visual separation
   }

   for(int i = 0; i < InpLiveRows; i++)
   {
      // Row A: Info + Close + 50%
      Place(PFX+"LIV_INFO_"+IntegerToString(i), x0,                  y, wide4,  H);
      Place(PFX+"LIV_C_"+IntegerToString(i),    x0+wide4+gap,        y, W,      H);
      Place(PFX+"LIV_H_"+IntegerToString(i),    x0+wide4+W+2*gap,    y, W,      H);
      y += rH;

      // Row B: SL_lbl + SL_edit + TP_lbl + TP_edit + Set + BE
      int sX = x0;
      Place(PFX+"LIV_SLL_"+IntegerToString(i), sX,                                y, lblW,  H);
      Place(PFX+"LIV_SLE_"+IntegerToString(i), sX+lblW+gap,                       y, editW, H);
      Place(PFX+"LIV_TPL_"+IntegerToString(i), sX+lblW+editW+2*gap,               y, lblW,  H);
      Place(PFX+"LIV_TPE_"+IntegerToString(i), sX+2*lblW+editW+3*gap,             y, editW, H);
      Place(PFX+"LIV_S_"+IntegerToString(i),   sX+2*lblW+2*editW+4*gap,           y, W,     H);
      Place(PFX+"LIV_B_"+IntegerToString(i),   sX+2*lblW+2*editW+W+5*gap,         y, W,     H);
      y += rH;
   }
   Place(PFX+"FOOTER_VER", g_panelX + InpFramePad, y, InnerW(), 16);
   y += 16;
   int totalH = (y - g_panelY) - gap + pad;
   Place(PFX+"FRAME", g_panelX, g_panelY, FullW(), totalH);
   UpdateLiveTrades();
   ChartRedraw();
}

//+------------------------------------------------------------------+
//|  ACCOUNT INFO HELPERS                                             |
//+------------------------------------------------------------------+
datetime DayStart()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}
datetime WeekStart()
{
   datetime today = DayStart();
   MqlDateTime dt; TimeToStruct(today, dt);
   int dow = (int)dt.day_of_week;  // 0=Sun
   if(dow == 0) dow = 7;
   return today - (dow - 1) * 86400;
}
datetime MonthStart()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   dt.day = 1; dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}
datetime YearStart()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   dt.mon = 1; dt.day = 1; dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}
double CalculatePnLSince(datetime from)
{
   if(!HistorySelect(from, TimeCurrent())) return 0.0;
   double sum = 0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      // Only count realized P&L (closing deals)
      long entry = HistoryDealGetInteger(t, DEAL_ENTRY);
      if(entry == DEAL_ENTRY_IN) continue;  // skip opening deals
      sum += HistoryDealGetDouble(t, DEAL_PROFIT)
           + HistoryDealGetDouble(t, DEAL_SWAP)
           + HistoryDealGetDouble(t, DEAL_COMMISSION);
   }
   return sum;
}
double OpenPositionsPnL()
{
   double sum = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      sum += PositionGetDouble(POSITION_PROFIT)
           + PositionGetDouble(POSITION_SWAP)
           + PositionGetDouble(POSITION_COMMISSION);
   }
   return sum;
}
string FormatMoney(double v)
{
   string sign = (v >= 0) ? "+" : "-";
   return sign + "$" + DoubleToString(MathAbs(v), 2);
}

//+------------------------------------------------------------------+
//|  ACCOUNT TAB LAYOUT & UPDATE                                      |
//+------------------------------------------------------------------+
void HideAccount()
{
   string keys[] = {
      "ACC_SEC1","ACC_BAL_L","ACC_BAL_V","ACC_EQU_L","ACC_EQU_V",
      "ACC_FRE_L","ACC_FRE_V","ACC_MAR_L","ACC_MAR_V","ACC_LEV_L","ACC_LEV_V",
      "ACC_SEC2","ACC_OPN_L","ACC_OPN_V","ACC_DAY_L","ACC_DAY_V",
      "ACC_WEK_L","ACC_WEK_V","ACC_MTH_L","ACC_MTH_V",
      "ACC_YR_L","ACC_YR_V","ACC_ALL_L","ACC_ALL_V"
   };
   for(int i = 0; i < ArraySize(keys); i++) HideObj(PFX+keys[i]);
}

void LayoutAccount()
{
   int W=g_btnW, H=InpBtnH, gap=InpGap, pad=InpFramePad;
   int rH = H + gap;
   int innerW = InnerW();

   int x0 = g_panelX + pad;
   int y  = g_panelY + pad;

   PlaceHeader(x0, y, innerW);
   y += HEADER_H + gap;
   PlaceInfoRow(x0, y, innerW);

   HideTradingObjects();
   for(int i = 0; i < InpHistoryRows; i++)
   {
      HideObj(PFX+"HIS_T_"+IntegerToString(i));
      HideObj(PFX+"HIS_A_"+IntegerToString(i));
      HideObj(PFX+"HIS_S_"+IntegerToString(i));
      HideObj(PFX+"HIS_X_"+IntegerToString(i));
   }
   for(int i = 0; i < 20; i++)
   {
      HideObj(PFX+"HLP_T_"+IntegerToString(i));
      HideObj(PFX+"HLP_D_"+IntegerToString(i));
   }
   for(int i = 0; i < InpLiveRows; i++)
   {
      HideObj(PFX+"LIV_INFO_"+IntegerToString(i));
      HideObj(PFX+"LIV_C_"+IntegerToString(i));
      HideObj(PFX+"LIV_H_"+IntegerToString(i));
      HideObj(PFX+"LIV_B_"+IntegerToString(i));
      HideObj(PFX+"LIV_SLE_"+IntegerToString(i));
      HideObj(PFX+"LIV_TPE_"+IntegerToString(i));
      HideObj(PFX+"LIV_S_"+IntegerToString(i));
      HideObj(PFX+"LIV_SLL_"+IntegerToString(i));
      HideObj(PFX+"LIV_TPL_"+IntegerToString(i));
   }
   HideObj(PFX+"BULK_HDR"); HideObj(PFX+"BULK_SLL"); HideObj(PFX+"BULK_TPL");
   HideObj(PFX+"BULK_SLE"); HideObj(PFX+"BULK_TPE"); HideObj(PFX+"BULK_S");
   HideObj(PFX+"BULK_SYM_DISP"); HideObj(PFX+"BULK_DIV");

   int lblW = 3*W + 2*gap;          // label = 3 cells
   int valW = innerW - lblW - gap;  // value = remaining

   // Section: ACCOUNT
   Place(PFX+"ACC_SEC1", x0, y, innerW, H); y += rH;
   string accRows1L[] = {"ACC_BAL_L","ACC_EQU_L","ACC_FRE_L","ACC_MAR_L","ACC_LEV_L"};
   string accRows1V[] = {"ACC_BAL_V","ACC_EQU_V","ACC_FRE_V","ACC_MAR_V","ACC_LEV_V"};
   for(int i = 0; i < ArraySize(accRows1L); i++)
   {
      Place(PFX+accRows1L[i], x0,            y, lblW, H);
      Place(PFX+accRows1V[i], x0+lblW+gap,   y, valW, H);
      y += rH;
   }

   // Section: PROFIT / LOSS
   Place(PFX+"ACC_SEC2", x0, y, innerW, H); y += rH;
   string accRows2L[] = {"ACC_OPN_L","ACC_DAY_L","ACC_WEK_L","ACC_MTH_L","ACC_YR_L","ACC_ALL_L"};
   string accRows2V[] = {"ACC_OPN_V","ACC_DAY_V","ACC_WEK_V","ACC_MTH_V","ACC_YR_V","ACC_ALL_V"};
   for(int i = 0; i < ArraySize(accRows2L); i++)
   {
      Place(PFX+accRows2L[i], x0,            y, lblW, H);
      Place(PFX+accRows2V[i], x0+lblW+gap,   y, valW, H);
      y += rH;
   }

   Place(PFX+"FOOTER_VER", g_panelX + InpFramePad, y, InnerW(), 16);
   y += 16;
   int totalH = (y - g_panelY) - gap + pad;
   Place(PFX+"FRAME", g_panelX, g_panelY, FullW(), totalH);
   UpdateAccount();
   ChartRedraw();
}

void UpdateAccount()
{
   if(g_currentTab != TAB_ACC) return;
   string ccy = AccountInfoString(ACCOUNT_CURRENCY);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double equ = AccountInfoDouble(ACCOUNT_EQUITY);
   double mar = AccountInfoDouble(ACCOUNT_MARGIN);
   double frm = AccountInfoDouble(ACCOUNT_FREEMARGIN);
   long   lev = AccountInfoInteger(ACCOUNT_LEVERAGE);

   SetText(PFX+"ACC_BAL_V", DoubleToString(bal, 2) + " " + ccy);
   SetText(PFX+"ACC_EQU_V", DoubleToString(equ, 2) + " " + ccy);
   SetText(PFX+"ACC_FRE_V", DoubleToString(frm, 2) + " " + ccy);
   SetText(PFX+"ACC_MAR_V", DoubleToString(mar, 2) + " " + ccy);
   SetText(PFX+"ACC_LEV_V", "1:" + IntegerToString((int)lev));

   double pnlOpen  = OpenPositionsPnL();
   double pnlDay   = CalculatePnLSince(DayStart());
   double pnlWeek  = CalculatePnLSince(WeekStart());
   double pnlMonth = CalculatePnLSince(MonthStart());
   double pnlYear  = CalculatePnLSince(YearStart());
   double pnlAll   = CalculatePnLSince(0);

   SetText(PFX+"ACC_OPN_V", FormatMoney(pnlOpen));
   SetText(PFX+"ACC_DAY_V", FormatMoney(pnlDay));
   SetText(PFX+"ACC_WEK_V", FormatMoney(pnlWeek));
   SetText(PFX+"ACC_MTH_V", FormatMoney(pnlMonth));
   SetText(PFX+"ACC_YR_V",  FormatMoney(pnlYear));
   SetText(PFX+"ACC_ALL_V", FormatMoney(pnlAll));

   SetTC(PFX+"ACC_OPN_V", pnlOpen  >= 0 ? COL_PNL_POS : COL_PNL_NEG);
   SetTC(PFX+"ACC_DAY_V", pnlDay   >= 0 ? COL_PNL_POS : COL_PNL_NEG);
   SetTC(PFX+"ACC_WEK_V", pnlWeek  >= 0 ? COL_PNL_POS : COL_PNL_NEG);
   SetTC(PFX+"ACC_MTH_V", pnlMonth >= 0 ? COL_PNL_POS : COL_PNL_NEG);
   SetTC(PFX+"ACC_YR_V",  pnlYear  >= 0 ? COL_PNL_POS : COL_PNL_NEG);
   SetTC(PFX+"ACC_ALL_V", pnlAll   >= 0 ? COL_PNL_POS : COL_PNL_NEG);
   ChartRedraw();
}

//+------------------------------------------------------------------+
void RenderHistory()
{
   int total = ArraySize(g_history);
   int rows  = InpHistoryRows;
   // Clamp offset
   int maxOffset = MathMax(0, total - rows);
   if(g_histScrollOffset > maxOffset) g_histScrollOffset = maxOffset;
   if(g_histScrollOffset < 0) g_histScrollOffset = 0;

   // Header text with position counter
   if(total == 0)
      SetText(PFX+"HIS_HDR", "HISTORY (empty)");
   else
   {
      int firstShown = g_histScrollOffset + 1;
      int lastShown  = MathMin(g_histScrollOffset + rows, total);
      SetText(PFX+"HIS_HDR",
              "HISTORY  ("+IntegerToString(firstShown)+"-"+IntegerToString(lastShown)+
              " of "+IntegerToString(total)+")");
   }
   for(int i = 0; i < rows; i++)
   {
      int histIdx = total - 1 - i - g_histScrollOffset;
      string tName = PFX+"HIS_T_"+IntegerToString(i);
      string aName = PFX+"HIS_A_"+IntegerToString(i);
      string sName = PFX+"HIS_S_"+IntegerToString(i);
      string xName = PFX+"HIS_X_"+IntegerToString(i);
      if(histIdx < 0 || histIdx >= total)
      {
         SetText(tName, ""); SetText(aName, "");
         SetText(sName, ""); SetText(xName, "");
         SetBG(xName, COL_STOP_OFF); SetBG(sName, COL_LABEL);
         continue;
      }
      SetText(tName, TimeToString(g_history[histIdx].time, TIME_MINUTES|TIME_SECONDS));
      SetText(aName, g_history[histIdx].text);
      if(g_history[histIdx].active)
      { SetText(sName, "RUNNING"); SetBG(sName, COL_ACTIVE);
        SetText(xName, "Stop");    SetBG(xName, COL_STOP_BTN); }
      else
      { SetText(sName, "done"); SetBG(sName, COL_LABEL);
        SetText(xName, "");     SetBG(xName, COL_STOP_OFF); }
   }
   ChartRedraw();
}

//+------------------------------------------------------------------+
//|  LIVE TRADES — populate rows for target symbol                    |
//+------------------------------------------------------------------+
void UpdateLiveTrades()
{
   if(g_currentTab != TAB_LIVE) return;
   ulong tickets[];
   CollectAllTickets(tickets);
   ArrayResize(g_liveTickets, InpLiveRows);
   if(ArraySize(g_liveTicketsCache) != InpLiveRows) ArrayResize(g_liveTicketsCache, InpLiveRows);
   int rows = InpLiveRows;
   int n = ArraySize(tickets);
   // Clamp scroll offset
   int maxOffset = MathMax(0, n - rows);
   if(g_liveScrollOffset > maxOffset) g_liveScrollOffset = maxOffset;
   if(g_liveScrollOffset < 0) g_liveScrollOffset = 0;
   // Header text with counter
   if(n == 0)
      SetText(PFX+"LIV_HDR", "LIVE TRADES (none open)");
   else
   {
      int firstShown = g_liveScrollOffset + 1;
      int lastShown  = MathMin(g_liveScrollOffset + rows, n);
      SetText(PFX+"LIV_HDR",
              "LIVE TRADES  ("+IntegerToString(firstShown)+"-"+IntegerToString(lastShown)+
              " of "+IntegerToString(n)+")");
   }
   for(int i = 0; i < rows; i++)
   {
      string iName = PFX+"LIV_INFO_"+IntegerToString(i);
      string cName = PFX+"LIV_C_"+IntegerToString(i);
      string hName = PFX+"LIV_H_"+IntegerToString(i);
      string bName = PFX+"LIV_B_"+IntegerToString(i);
      string slName = PFX+"LIV_SLE_"+IntegerToString(i);
      string tpName = PFX+"LIV_TPE_"+IntegerToString(i);
      string sName  = PFX+"LIV_S_"+IntegerToString(i);
      string sllName = PFX+"LIV_SLL_"+IntegerToString(i);
      string tplName = PFX+"LIV_TPL_"+IntegerToString(i);
      ulong newTicket = ((i + g_liveScrollOffset) < n) ? tickets[i + g_liveScrollOffset] : 0;
      bool ticketChanged = (newTicket != g_liveTicketsCache[i]);
      g_liveTicketsCache[i] = newTicket;
      g_liveTickets[i]      = newTicket;
      if(newTicket == 0)
      {
         SetText(iName, ""); SetBG(iName, COL_LABEL);
         SetBG(cName, COL_STOP_OFF); SetText(cName, "");
         SetBG(hName, COL_STOP_OFF); SetText(hName, "");
         SetBG(bName, COL_STOP_OFF); SetText(bName, "");
         SetBG(sName, COL_STOP_OFF); SetText(sName, "");
         ObjectSetString(0, slName, OBJPROP_TEXT, "");
         ObjectSetString(0, tpName, OBJPROP_TEXT, "");
         ObjectSetInteger(0, slName, OBJPROP_BGCOLOR, COL_LABEL);
         ObjectSetInteger(0, tpName, OBJPROP_BGCOLOR, COL_LABEL);
         SetText(sllName, ""); SetBG(sllName, COL_STOP_OFF);
         SetText(tplName, ""); SetBG(tplName, COL_STOP_OFF);
         continue;
      }
      if(!PositionSelectByTicket(newTicket)) continue;
      string posSym = PositionGetString(POSITION_SYMBOL);
      int    digits = (int)SymbolInfoInteger(posSym, SYMBOL_DIGITS);
      long type   = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol  = PositionGetDouble(POSITION_VOLUME);
      double curSL= PositionGetDouble(POSITION_SL);
      double curTP= PositionGetDouble(POSITION_TP);
      double pnl  = PositionGetDouble(POSITION_PROFIT) +
                    PositionGetDouble(POSITION_SWAP) +
                    PositionGetDouble(POSITION_COMMISSION);
      string side = (type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      // In ALL mode show symbol in the row (since multiple symbols may be listed)
      string prefix = IsAllMode() ? (posSym + " ") : "";
      string text = prefix + side + " " + DoubleToString(vol, 2) + " @" + DoubleToString(open, digits) +
                    "  " + (pnl >= 0 ? "+$" : "-$") + DoubleToString(MathAbs(pnl), 2);
      SetText(iName, text);
      SetBG(iName, (type == POSITION_TYPE_BUY) ? COL_INFO_BG : COL_LABEL);
      SetTC(iName, pnl >= 0 ? COL_PNL_POS : COL_PNL_NEG);
      SetBG(cName, COL_DANGER); SetText(cName, "Close");
      SetBG(hName, COL_CLOSE);  SetText(hName, "50%");
      SetBG(bName, COL_ACTION); SetText(bName, "BE");
      SetBG(sName, COL_ACTION); SetText(sName, "Set");
      SetText(sllName, "SL"); SetBG(sllName, COL_LABEL); SetTC(sllName, COL_TXT_MUTED);
      SetText(tplName, "TP"); SetBG(tplName, COL_LABEL); SetTC(tplName, COL_TXT_MUTED);
      ObjectSetInteger(0, slName, OBJPROP_BGCOLOR, COL_INFO_BG);
      ObjectSetInteger(0, tpName, OBJPROP_BGCOLOR, COL_INFO_BG);
      // Only fill edit fields if THIS row got a new ticket — don't stomp on user typing
      if(ticketChanged)
      {
         ObjectSetString(0, slName, OBJPROP_TEXT, curSL > 0 ? DoubleToString(curSL, digits) : "");
         ObjectSetString(0, tpName, OBJPROP_TEXT, curTP > 0 ? DoubleToString(curTP, digits) : "");
      }
   }
   ChartRedraw();
}

//+------------------------------------------------------------------+
void SwitchTab(string newTab)
{
   CloseSymDropdown();
   CloseBulkDropdown();
   // Reset scroll when entering History or Live
   if(newTab != g_currentTab)
   {
      if(newTab == TAB_HISTORY) g_histScrollOffset = 0;
      if(newTab == TAB_LIVE)    g_liveScrollOffset = 0;
   }
   g_currentTab = newTab;
   // Active tab: filled electric-blue pill + dark text; inactive: dark navy + muted text
   SetBG(PFX+"TAB_TRD", (newTab==TAB_TRADING)? COL_TAB_ON : COL_TAB_OFF);
   SetTC(PFX+"TAB_TRD", (newTab==TAB_TRADING)? COL_TXT_DARK : COL_TXT_MUTED);
   SetBG(PFX+"TAB_HIS", (newTab==TAB_HISTORY)? COL_TAB_ON : COL_TAB_OFF);
   SetTC(PFX+"TAB_HIS", (newTab==TAB_HISTORY)? COL_TXT_DARK : COL_TXT_MUTED);
   SetBG(PFX+"TAB_LIV", (newTab==TAB_LIVE)?    COL_TAB_ON : COL_TAB_OFF);
   SetTC(PFX+"TAB_LIV", (newTab==TAB_LIVE)?    COL_TXT_DARK : COL_TXT_MUTED);
   SetBG(PFX+"TAB_ACC", (newTab==TAB_ACCOUNT)? COL_TAB_ON : COL_TAB_OFF);
   SetTC(PFX+"TAB_ACC", (newTab==TAB_ACCOUNT)? COL_TXT_DARK : COL_TXT_MUTED);
   SetBG(PFX+"TAB_HLP", (newTab==TAB_HELP)?    COL_TAB_ON : COL_TAB_OFF);
   SetTC(PFX+"TAB_HLP", (newTab==TAB_HELP)?    COL_TXT_DARK : COL_TXT_MUTED);
   if(newTab == TAB_TRADING)      LayoutTrading();
   else if(newTab == TAB_HISTORY) LayoutHistory();
   else if(newTab == TAB_LIVE)    LayoutLive();
   else if(newTab == TAB_ACCOUNT) LayoutAccount();
   else                            LayoutHelp();
}

//+------------------------------------------------------------------+
//|  UPDATES                                                          |
//+------------------------------------------------------------------+
void UpdatePriceDisplay()
{
   if(g_currentTab != TAB_TRADING) return;
   string sym    = EffectiveSymbol();
   int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double bid    = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask    = SymbolInfoDouble(sym, SYMBOL_ASK);
   SetText(PFX+"PRICE_BUY",  "BUY  " + DoubleToString(ask, digits));
   SetText(PFX+"PRICE_SELL", "SELL " + DoubleToString(bid, digits));
}
void UpdateInfoRow()
{
   SetText(PFX+"INFO_CHART", "Chart: " + g_chartSym);
   SetText(PFX+"INFO_TF",    "TF: "    + TFString());
   SetText(PFX+"INFO_TGT",   "Target: "+ g_targetSym);
}
void UpdateLotDisplay()
{
   string lot = DoubleToString(g_lotSize, 2);
   SetText(PFX+"LOT_DISP", "Lot: " + lot);
   SetText(PFX+"MKT_BUY",  "BUY  " + lot);
   SetText(PFX+"MKT_SELL", "SELL " + lot);
}
void UpdateBeDisplay()
{
   SetText(PFX+"BEPT_DISP", "$" + DoubleToString(g_bePerOffset, 2));
}
void UpdateSymbolDisplay() { SetText(PFX+"SYM_DISP", g_targetSym); }

string ModeLabel(string mode)
{
   if(mode == "TRL_FAST")  return "Trail Fast";
   if(mode == "TRL_MED")   return "Trail Med";
   if(mode == "TRL_SLOW")  return "Trail Slow";
   return mode;
}
void UpdateStatus()
{
   string txt = "Nothing active";
   if(g_activeMode != "")
   {
      int n = CountLivingActiveTickets();
      txt = "Active: " + ModeLabel(g_activeMode) +
            " (" + IntegerToString(n) + " trade" + (n==1?"":"s") + ") " +
            g_targetSym;
   }
   SetText(PFX+"STATUS", txt);
   SetBG(PFX+"STOP", (g_activeMode != "") ? COL_STOP_BTN : COL_STOP_OFF);
}
void RefreshButtonStates()
{
   SetBG(PFX+"TRL_FAST",  (g_activeMode=="TRL_FAST") ? COL_ACTIVE : COL_TRAIL);
   SetBG(PFX+"TRL_MED",   (g_activeMode=="TRL_MED")  ? COL_ACTIVE : COL_TRAIL);
   SetBG(PFX+"TRL_SLOW",  (g_activeMode=="TRL_SLOW") ? COL_ACTIVE : COL_TRAIL);
   ChartRedraw();
}
void UpdateDot()
{
   datetime now = TimeCurrent();
   if(now != g_lastBlink)
   {
      g_lastBlink = now;
      g_dotBright = !g_dotBright;
      ObjectSetInteger(0, PFX+"DOT", OBJPROP_COLOR,
                       g_dotBright ? COL_STATUS_DOT : COL_DOT_DIM);
      ChartRedraw();
   }
}

//+------------------------------------------------------------------+
//|  BE ONE-SHOT FUNCTIONS                                            |
//+------------------------------------------------------------------+
void ApplyBeWorstOnce(double dollarOffset)
{
   ulong tickets[];
   if(CollectAllTickets(tickets) == 0) return;
   int n = ArraySize(tickets);

   // For ALL mode, behave per-trade (worst-entry doesn't make sense across symbols).
   if(IsAllMode())
   {
      ApplyBePerTradeOnce(dollarOffset);
      return;
   }

   double worstBuy=0, worstSell=0, worstBuyVol=0, worstSellVol=0;
   bool hasBuy=false, hasSell=false;
   for(int k = 0; k < n; k++)
   {
      if(!PositionSelectByTicket(tickets[k])) continue;
      long type   = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol  = PositionGetDouble(POSITION_VOLUME);
      if(type == POSITION_TYPE_BUY)
      { if(!hasBuy || open > worstBuy) { worstBuy=open; worstBuyVol=vol; hasBuy=true; } }
      else if(type == POSITION_TYPE_SELL)
      { if(!hasSell || open < worstSell) { worstSell=open; worstSellVol=vol; hasSell=true; } }
   }

   double offBuy  = hasBuy  ? DollarToPriceOffset(g_targetSym, dollarOffset, worstBuyVol)  : 0;
   double offSell = hasSell ? DollarToPriceOffset(g_targetSym, dollarOffset, worstSellVol) : 0;

   int    digits = (int)SymbolInfoInteger(g_targetSym, SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(g_targetSym, SYMBOL_POINT);
   double bid    = SymbolInfoDouble(g_targetSym, SYMBOL_BID);
   double ask    = SymbolInfoDouble(g_targetSym, SYMBOL_ASK);
   long   stops  = SymbolInfoInteger(g_targetSym, SYMBOL_TRADE_STOPS_LEVEL);
   double minD   = (double)stops * point;
   double slBuy  = hasBuy  ? NormalizeDouble(worstBuy  + offBuy,  digits) : 0;
   double slSell = hasSell ? NormalizeDouble(worstSell - offSell, digits) : 0;
   if(hasBuy  && slBuy  >= bid - minD) hasBuy  = false;
   if(hasSell && slSell <= ask + minD) hasSell = false;

   int applied = 0;
   for(int k = 0; k < n; k++)
   {
      ulong t = tickets[k];
      if(!PositionSelectByTicket(t)) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      double newSL = curSL;
      if(type == POSITION_TYPE_BUY && hasBuy)
      {
         newSL = slBuy;
         if(InpOnlyImprove && curSL > 0 && newSL <= curSL) continue;
      }
      else if(type == POSITION_TYPE_SELL && hasSell)
      {
         newSL = slSell;
         if(InpOnlyImprove && curSL > 0 && newSL >= curSL) continue;
      }
      else continue;
      if(MathAbs(newSL - curSL) < point * 0.5) continue;
      if(trade.PositionModify(t, newSL, curTP)) applied++;
   }
   AddHistory("BE All $" + DoubleToString(dollarOffset, 2) +
              " | " + IntegerToString(applied) + "/" + IntegerToString(n) +
              " trades | " + g_targetSym);
}

void ApplyBePerTradeOnce(double dollarOffset)
{
   ulong tickets[];
   int n = CollectAllTickets(tickets);
   if(n == 0) return;
   int applied = 0;
   for(int k = 0; k < n; k++)
   {
      ulong t = tickets[k];
      if(!PositionSelectByTicket(t)) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double point  = SymbolInfoDouble(sym, SYMBOL_POINT);
      double bid    = SymbolInfoDouble(sym, SYMBOL_BID);
      double ask    = SymbolInfoDouble(sym, SYMBOL_ASK);
      long   stops  = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
      double minD   = (double)stops * point;
      long type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol  = PositionGetDouble(POSITION_VOLUME);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      double po    = DollarToPriceOffset(sym, dollarOffset, vol);
      double newSL;
      if(type == POSITION_TYPE_BUY)
      {
         newSL = NormalizeDouble(open + po, digits);
         if(newSL >= bid - minD) continue;
         if(InpOnlyImprove && curSL > 0 && newSL <= curSL) continue;
      }
      else if(type == POSITION_TYPE_SELL)
      {
         newSL = NormalizeDouble(open - po, digits);
         if(newSL <= ask + minD) continue;
         if(InpOnlyImprove && curSL > 0 && newSL >= curSL) continue;
      }
      else continue;
      if(MathAbs(newSL - curSL) < point * 0.5) continue;
      if(trade.PositionModify(t, newSL, curTP)) applied++;
   }
   AddHistory("BE/Trade $" + DoubleToString(dollarOffset, 2) +
              " | " + IntegerToString(applied) + "/" + IntegerToString(n) +
              " trades | " + g_targetSym);
}

//+------------------------------------------------------------------+
//|  TRAIL MODES (still persistent)                                   |
//+------------------------------------------------------------------+
void SetActiveMode(string mode)
{
   if(g_activeHistIdx >= 0) MarkHistoryDone(g_activeHistIdx);
   g_activeMode = mode;
   SnapshotActiveTickets();
   g_activeHistIdx = AddHistory(ModeLabel(mode) + " | " +
                                IntegerToString(ArraySize(g_activeTickets)) + " trades | " +
                                g_targetSym, true, mode);
   ApplyActiveMode();
   RefreshButtonStates();
   UpdateStatus();
}
void StopActiveMode()
{
   if(g_activeMode == "") return;
   if(g_activeHistIdx >= 0) MarkHistoryDone(g_activeHistIdx);
   g_activeMode = "";
   g_activeHistIdx = -1;
   ArrayResize(g_activeTickets, 0);
   RefreshButtonStates();
   UpdateStatus();
}
void ApplyActiveMode()
{
   if(g_activeMode == "" || ArraySize(g_activeTickets) == 0) return;
   // Auto-stop if all snapshot trades are closed
   if(CountLivingActiveTickets() == 0)
   {
      AddHistory(ModeLabel(g_activeMode) + " auto-stopped (all trades closed) | " + g_targetSym);
      StopActiveMode();
      return;
   }
   if(IsAllMode())
   {
      if(g_activeMode == "TRL_FAST") ApplyTrailingPerTrade(TRAIL_FAST_START, TRAIL_FAST_STEP, TRAIL_FAST_ADD);
      else if(g_activeMode == "TRL_MED")  ApplyTrailingPerTrade(TRAIL_MED_START,  TRAIL_MED_STEP,  TRAIL_MED_ADD);
      else if(g_activeMode == "TRL_SLOW") ApplyTrailingPerTrade(TRAIL_SLOW_START, TRAIL_SLOW_STEP, TRAIL_SLOW_ADD);
      return;
   }
   if(g_activeMode == "TRL_FAST") ApplyTrailing(TRAIL_FAST_START, TRAIL_FAST_STEP, TRAIL_FAST_ADD);
   else if(g_activeMode == "TRL_MED")  ApplyTrailing(TRAIL_MED_START,  TRAIL_MED_STEP,  TRAIL_MED_ADD);
   else if(g_activeMode == "TRL_SLOW") ApplyTrailing(TRAIL_SLOW_START, TRAIL_SLOW_STEP, TRAIL_SLOW_ADD);
}

void ApplyTrailingPerTrade(double start, double step, double add)
{
   int sn = ArraySize(g_activeTickets);
   for(int k = 0; k < sn; k++)
   {
      ulong t = g_activeTickets[k];
      if(!PositionSelectByTicket(t)) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      double bid    = SymbolInfoDouble(sym, SYMBOL_BID);
      double ask    = SymbolInfoDouble(sym, SYMBOL_ASK);
      int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double point  = SymbolInfoDouble(sym, SYMBOL_POINT);
      long   stops  = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
      double minD   = (double)stops * point;
      long   type   = PositionGetInteger(POSITION_TYPE);
      double open   = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSL  = PositionGetDouble(POSITION_SL);
      double curTP  = PositionGetDouble(POSITION_TP);
      double offset, newSL;
      if(type == POSITION_TYPE_BUY)
      {
         double mv = bid - open;
         if(mv < start) continue;
         offset = ComputeTrailOffset(mv, start, step, add);
         newSL = NormalizeDouble(open + offset, digits);
         if(newSL >= bid - minD) continue;
         if(InpOnlyImprove && curSL > 0 && newSL <= curSL) continue;
      }
      else
      {
         double mv = open - ask;
         if(mv < start) continue;
         offset = ComputeTrailOffset(mv, start, step, add);
         newSL = NormalizeDouble(open - offset, digits);
         if(newSL <= ask + minD) continue;
         if(InpOnlyImprove && curSL > 0 && newSL >= curSL) continue;
      }
      if(MathAbs(newSL - curSL) < point * 0.5) continue;
      trade.PositionModify(t, newSL, curTP);
   }
}

double ComputeTrailOffset(double movement, double start, double step, double add)
{
   if(movement < step) return start;
   int steps = (int)MathFloor(movement / step);
   return start + add * (double)steps;
}
void ApplyTrailing(double start, double step, double add)
{
   double bid = SymbolInfoDouble(g_targetSym, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_targetSym, SYMBOL_ASK);
   double worstBuy=0, worstSell=0; bool hasBuy=false, hasSell=false;
   int sn = ArraySize(g_activeTickets);
   for(int k = 0; k < sn; k++)
   {
      ulong t = g_activeTickets[k];
      if(!PositionSelectByTicket(t)) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_targetSym) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      if(type == POSITION_TYPE_BUY)
      { if(!hasBuy || open > worstBuy) { worstBuy=open; hasBuy=true; } }
      else if(type == POSITION_TYPE_SELL)
      { if(!hasSell || open < worstSell) { worstSell=open; hasSell=true; } }
   }
   if(!hasBuy && !hasSell) return;
   double offBuy  = hasBuy  ? ComputeTrailOffset(bid - worstBuy,  start, step, add) : start;
   double offSell = hasSell ? ComputeTrailOffset(worstSell - ask, start, step, add) : start;
   SetSLWorstTrail(offBuy, offSell);
}

void SetSLWorstTrail(double offsetBuy, double offsetSell)
{
   int    digits = (int)SymbolInfoInteger(g_targetSym, SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(g_targetSym, SYMBOL_POINT);
   double bid    = SymbolInfoDouble(g_targetSym, SYMBOL_BID);
   double ask    = SymbolInfoDouble(g_targetSym, SYMBOL_ASK);
   long   stops  = SymbolInfoInteger(g_targetSym, SYMBOL_TRADE_STOPS_LEVEL);
   double minD   = (double)stops * point;
   double worstBuy=0, worstSell=0; bool hasBuy=false, hasSell=false;
   int sn = ArraySize(g_activeTickets);
   for(int k = 0; k < sn; k++)
   {
      ulong t = g_activeTickets[k];
      if(!PositionSelectByTicket(t)) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_targetSym) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      if(type == POSITION_TYPE_BUY)
      { if(!hasBuy || open > worstBuy) { worstBuy=open; hasBuy=true; } }
      else if(type == POSITION_TYPE_SELL)
      { if(!hasSell || open < worstSell) { worstSell=open; hasSell=true; } }
   }
   if(!hasBuy && !hasSell) return;
   double slBuy  = hasBuy  ? NormalizeDouble(worstBuy  + offsetBuy,  digits) : 0;
   double slSell = hasSell ? NormalizeDouble(worstSell - offsetSell, digits) : 0;
   if(hasBuy  && slBuy  >= bid - minD) hasBuy  = false;
   if(hasSell && slSell <= ask + minD) hasSell = false;
   if(!hasBuy && !hasSell) return;
   for(int k = 0; k < sn; k++)
   {
      ulong t = g_activeTickets[k];
      if(!PositionSelectByTicket(t)) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_targetSym) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      double newSL = curSL;
      if(type == POSITION_TYPE_BUY && hasBuy)
      {
         newSL = slBuy;
         if(InpOnlyImprove && curSL > 0 && newSL <= curSL) continue;
      }
      else if(type == POSITION_TYPE_SELL && hasSell)
      {
         newSL = slSell;
         if(InpOnlyImprove && curSL > 0 && newSL >= curSL) continue;
      }
      else continue;
      if(MathAbs(newSL - curSL) < point * 0.5) continue;
      trade.PositionModify(t, newSL, curTP);
   }
}

//+------------------------------------------------------------------+
//|  CLOSE FUNCTIONS                                                  |
//+------------------------------------------------------------------+
int ClosePositionsFast(ENUM_POSITION_TYPE wt, bool any)
{
   ulong tickets[]; int n = CollectTickets(tickets, wt, any);
   if(n == 0) return 0;
   trade.SetAsyncMode(true);
   int sent = 0;
   for(int i = 0; i < n; i++) if(trade.PositionClose(tickets[i])) sent++;
   trade.SetAsyncMode(false);
   string what = any ? "ALL" : (wt == POSITION_TYPE_BUY ? "BUY" : "SELL");
   AddHistory("Close " + what + " (" + IntegerToString(sent) + ") " + g_targetSym);
   return sent;
}
int CloseByProfitStatus(bool wantProfit)
{
   ulong tickets[]; int n = CollectByProfit(tickets, wantProfit);
   if(n == 0) return 0;
   trade.SetAsyncMode(true);
   int sent = 0;
   for(int i = 0; i < n; i++) if(trade.PositionClose(tickets[i])) sent++;
   trade.SetAsyncMode(false);
   string what = wantProfit ? "Close Profits" : "Close Loss";
   AddHistory(what + " (" + IntegerToString(sent) + ") " + g_targetSym);
   return sent;
}

void SortByWorst(PosInfo &arr[], bool desc)
{
   int n = ArraySize(arr);
   for(int i = 0; i < n-1; i++)
      for(int j = 0; j < n-1-i; j++)
      {
         bool sw = desc ? (arr[j].entry < arr[j+1].entry) : (arr[j].entry > arr[j+1].entry);
         if(sw) { PosInfo tmp=arr[j]; arr[j]=arr[j+1]; arr[j+1]=tmp; }
      }
}
int CloseFraction(PosInfo &arr[], double pct, double step, double minVol)
{
   int n = ArraySize(arr);
   if(n == 0) return 0;
   double total = 0; for(int i=0;i<n;i++) total += arr[i].volume;
   if(total <= 0) return 0;
   double remaining = total * pct;
   double eps = step * 0.5;
   int actions = 0;
   for(int i = 0; i < n; i++)
   {
      if(remaining <= eps) break;
      double vol = arr[i].volume;
      if(vol <= remaining + eps)
      { if(trade.PositionClose(arr[i].ticket)) { remaining -= vol; actions++; } }
      else
      {
         double partial = MathFloor((remaining + step*0.001) / step) * step;
         double leftover = vol - partial;
         if(partial < minVol) break;
         if(leftover < minVol)
         { if(trade.PositionClose(arr[i].ticket)) { remaining -= vol; actions++; } }
         else
         { if(trade.PositionClosePartial(arr[i].ticket, partial)) { remaining -= partial; actions++; } }
         break;
      }
   }
   return actions;
}

int CloseByPercent(double pct)
{
   bool all = IsAllMode();
   string sym = EffectiveSymbol();
   double step   = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double minVol = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   if(step <= 0) step = 0.01;
   if(minVol <= 0) minVol = 0.01;
   PosInfo buys[], sells[]; ArrayResize(buys, 0); ArrayResize(sells, 0);
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if(!all && PositionGetString(POSITION_SYMBOL) != sym) continue;
      if(InpMagic >= 0 && PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      PosInfo p; p.ticket=t; p.entry=PositionGetDouble(POSITION_PRICE_OPEN);
      p.volume=PositionGetDouble(POSITION_VOLUME);
      long type = PositionGetInteger(POSITION_TYPE);
      if(type == POSITION_TYPE_BUY) { int n=ArraySize(buys); ArrayResize(buys,n+1); buys[n]=p; }
      else if(type == POSITION_TYPE_SELL) { int n=ArraySize(sells); ArrayResize(sells,n+1); sells[n]=p; }
   }
   SortByWorst(buys, true);
   SortByWorst(sells, false);
   trade.SetAsyncMode(true);
   int a = CloseFraction(buys, pct, step, minVol);
   int b = CloseFraction(sells, pct, step, minVol);
   trade.SetAsyncMode(false);
   int total = a + b;
   AddHistory("Close " + IntegerToString((int)(pct*100)) + "% (" + IntegerToString(total) + ") " + g_targetSym);
   return total;
}

void ClosePercentThenBE(double pct)
{
   CloseByPercent(pct);
   Sleep(200);
   ApplyBeWorstOnce(InpComboBeOffset);
}

//+------------------------------------------------------------------+
//|  PER-TRADE LIVE ACTIONS                                           |
//+------------------------------------------------------------------+
void LiveClose(int row)
{
   if(row < 0 || row >= ArraySize(g_liveTickets)) return;
   ulong t = g_liveTickets[row];
   if(t == 0) return;
   if(trade.PositionClose(t))
   {
      if(PositionSelectByTicket(t))
      {
         AddHistory("Live Close " + IntegerToString((int)t) + " " + g_targetSym);
      }
      else
      {
         AddHistory("Live Close ticket " + IntegerToString((int)t) + " " + g_targetSym);
      }
   }
}
void LiveHalf(int row)
{
   if(row < 0 || row >= ArraySize(g_liveTickets)) return;
   ulong t = g_liveTickets[row];
   if(t == 0 || !PositionSelectByTicket(t)) return;
   double vol  = PositionGetDouble(POSITION_VOLUME);
   double step = SymbolInfoDouble(g_targetSym, SYMBOL_VOLUME_STEP);
   double min  = SymbolInfoDouble(g_targetSym, SYMBOL_VOLUME_MIN);
   if(step <= 0) step = 0.01;
   if(min  <= 0) min  = 0.01;
   double half = MathFloor((vol * 0.5) / step) * step;
   double rest = vol - half;
   if(half < min || rest < min)
   { trade.PositionClose(t); AddHistory("Live Close (small) " + g_targetSym); return; }
   if(trade.PositionClosePartial(t, half))
      AddHistory("Live 50% " + DoubleToString(half,2) + " of " + IntegerToString((int)t) + " " + g_targetSym);
}
void LiveBe(int row)
{
   if(row < 0 || row >= ArraySize(g_liveTickets)) return;
   ulong t = g_liveTickets[row];
   if(t == 0) { AddHistory("Live BE: no ticket in row " + IntegerToString(row)); return; }
   if(!PositionSelectByTicket(t))
   { AddHistory("Live BE: ticket " + IntegerToString((int)t) + " not found"); return; }
   string posSym = PositionGetString(POSITION_SYMBOL);
   long type   = PositionGetInteger(POSITION_TYPE);
   double open = PositionGetDouble(POSITION_PRICE_OPEN);
   double vol  = PositionGetDouble(POSITION_VOLUME);
   double curTP= PositionGetDouble(POSITION_TP);
   int    digits = (int)SymbolInfoInteger(posSym, SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(posSym, SYMBOL_POINT);
   double bid    = SymbolInfoDouble(posSym, SYMBOL_BID);
   double ask    = SymbolInfoDouble(posSym, SYMBOL_ASK);
   long   stops  = SymbolInfoInteger(posSym, SYMBOL_TRADE_STOPS_LEVEL);
   double minD   = (double)stops * point;
   double po     = DollarToPriceOffset(posSym, InpComboBeOffset, vol);
   double newSL;
   if(type == POSITION_TYPE_BUY)
   {
      newSL = NormalizeDouble(open + po, digits);
      if(newSL >= bid - minD)
      {
         AddHistory("Live BE skip #" + IntegerToString((int)t) +
                    " SL=" + DoubleToString(newSL,digits) +
                    " too close to Bid=" + DoubleToString(bid,digits));
         return;
      }
   }
   else
   {
      newSL = NormalizeDouble(open - po, digits);
      if(newSL <= ask + minD)
      {
         AddHistory("Live BE skip #" + IntegerToString((int)t) +
                    " SL=" + DoubleToString(newSL,digits) +
                    " too close to Ask=" + DoubleToString(ask,digits));
         return;
      }
   }
   if(trade.PositionModify(t, newSL, curTP))
   {
      AddHistory("Live BE $" + DoubleToString(InpComboBeOffset,2) +
                 " #" + IntegerToString((int)t) + " " + posSym);
   }
   else
   {
      uint rc = trade.ResultRetcode();
      AddHistory("Live BE FAIL #" + IntegerToString((int)t) +
                 " rc=" + IntegerToString((int)rc));
   }
}

void LiveBulkSet()
{
   if(g_bulkSym == "" || g_bulkSym == "ALL")
   {
      AddHistory("Bulk Set: pick a specific symbol first (use Bulk picker)");
      return;
   }
   string sym = g_bulkSym;
   int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double bid    = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask    = SymbolInfoDouble(sym, SYMBOL_ASK);

   string slStr = ObjectGetString(0, PFX+"BULK_SLE", OBJPROP_TEXT);
   string tpStr = ObjectGetString(0, PFX+"BULK_TPE", OBJPROP_TEXT);
   StringTrimLeft(slStr); StringTrimRight(slStr);
   StringTrimLeft(tpStr); StringTrimRight(tpStr);
   StringReplace(slStr, ",", ".");
   StringReplace(tpStr, ",", ".");

   double newSL = (StringLen(slStr) > 0) ? StringToDouble(slStr) : 0.0;
   double newTP = (StringLen(tpStr) > 0) ? StringToDouble(tpStr) : 0.0;
   if(newSL > 0) newSL = NormalizeDouble(newSL, digits);
   if(newTP > 0) newTP = NormalizeDouble(newTP, digits);
   if(newSL <= 0 && newTP <= 0)
   { AddHistory("Bulk Set: no SL/TP entered"); return; }

   int applied = 0, total = 0, rejected = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if(PositionGetString(POSITION_SYMBOL) != sym) continue;
      if(InpMagic >= 0 && PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      total++;
      long type = PositionGetInteger(POSITION_TYPE);

      // Auto-swap if both entered and look inverted for this trade's direction
      double finalSL = newSL, finalTP = newTP;
      if(finalSL > 0 && finalTP > 0)
      {
         if(type == POSITION_TYPE_BUY && finalSL > finalTP)
         { double tmp = finalSL; finalSL = finalTP; finalTP = tmp; }
         if(type == POSITION_TYPE_SELL && finalSL < finalTP)
         { double tmp = finalSL; finalSL = finalTP; finalTP = tmp; }
      }

      // Side validation
      bool ok = true;
      if(finalSL > 0)
      {
         if(type == POSITION_TYPE_BUY  && finalSL >= bid) ok = false;
         if(type == POSITION_TYPE_SELL && finalSL <= ask) ok = false;
      }
      if(finalTP > 0)
      {
         if(type == POSITION_TYPE_BUY  && finalTP <= ask) ok = false;
         if(type == POSITION_TYPE_SELL && finalTP >= bid) ok = false;
      }
      if(!ok) { rejected++; continue; }

      if(trade.PositionModify(t, finalSL, finalTP)) applied++;
   }
   AddHistory("Bulk Set on " + sym + ": " + IntegerToString(applied) + "/" +
              IntegerToString(total) + " applied" +
              (rejected > 0 ? " (" + IntegerToString(rejected) + " rejected)" : "") +
              " SL=" + (newSL>0?DoubleToString(newSL,digits):"0") +
              " TP=" + (newTP>0?DoubleToString(newTP,digits):"0"));
}

void LiveSet(int row)
{
   if(row < 0 || row >= ArraySize(g_liveTickets)) return;
   ulong t = g_liveTickets[row];
   if(t == 0) { AddHistory("Live Set: no ticket in row " + IntegerToString(row)); return; }
   if(!PositionSelectByTicket(t))
   { AddHistory("Live Set: ticket " + IntegerToString((int)t) + " not found"); return; }
   string posSym = PositionGetString(POSITION_SYMBOL);
   long   type   = PositionGetInteger(POSITION_TYPE);
   int    digits = (int)SymbolInfoInteger(posSym, SYMBOL_DIGITS);
   double bid    = SymbolInfoDouble(posSym, SYMBOL_BID);
   double ask    = SymbolInfoDouble(posSym, SYMBOL_ASK);

   string slStr = ObjectGetString(0, PFX+"LIV_SLE_"+IntegerToString(row), OBJPROP_TEXT);
   string tpStr = ObjectGetString(0, PFX+"LIV_TPE_"+IntegerToString(row), OBJPROP_TEXT);
   StringTrimLeft(slStr); StringTrimRight(slStr);
   StringTrimLeft(tpStr); StringTrimRight(tpStr);
   StringReplace(slStr, ",", ".");
   StringReplace(tpStr, ",", ".");

   double newSL = (StringLen(slStr) > 0) ? StringToDouble(slStr) : 0.0;
   double newTP = (StringLen(tpStr) > 0) ? StringToDouble(tpStr) : 0.0;
   if(newSL > 0) newSL = NormalizeDouble(newSL, digits);
   if(newTP > 0) newTP = NormalizeDouble(newTP, digits);

   //--- AUTO-SWAP if SL/TP look inverted for the trade direction
   bool swapped = false;
   if(newSL > 0 && newTP > 0)
   {
      if(type == POSITION_TYPE_BUY && newSL > newTP)
      { double tmp = newSL; newSL = newTP; newTP = tmp; swapped = true; }
      if(type == POSITION_TYPE_SELL && newSL < newTP)
      { double tmp = newSL; newSL = newTP; newTP = tmp; swapped = true; }
   }

   //--- VALIDATE sides relative to current price
   if(newSL > 0)
   {
      if(type == POSITION_TYPE_BUY && newSL >= bid)
      { AddHistory("Live Set REJECT #" + IntegerToString((int)t) +
                   " BUY: SL " + DoubleToString(newSL,digits) +
                   " must be BELOW Bid " + DoubleToString(bid,digits)); return; }
      if(type == POSITION_TYPE_SELL && newSL <= ask)
      { AddHistory("Live Set REJECT #" + IntegerToString((int)t) +
                   " SELL: SL " + DoubleToString(newSL,digits) +
                   " must be ABOVE Ask " + DoubleToString(ask,digits)); return; }
   }
   if(newTP > 0)
   {
      if(type == POSITION_TYPE_BUY && newTP <= ask)
      { AddHistory("Live Set REJECT #" + IntegerToString((int)t) +
                   " BUY: TP " + DoubleToString(newTP,digits) +
                   " must be ABOVE Ask " + DoubleToString(ask,digits)); return; }
      if(type == POSITION_TYPE_SELL && newTP >= bid)
      { AddHistory("Live Set REJECT #" + IntegerToString((int)t) +
                   " SELL: TP " + DoubleToString(newTP,digits) +
                   " must be BELOW Bid " + DoubleToString(bid,digits)); return; }
   }

   if(trade.PositionModify(t, newSL, newTP))
   {
      AddHistory((swapped?"Live Set (swapped) #":"Live Set #") + IntegerToString((int)t) +
                 " SL=" + (newSL>0 ? DoubleToString(newSL,digits) : "0") +
                 " TP=" + (newTP>0 ? DoubleToString(newTP,digits) : "0") +
                 " " + posSym);
      // Update displayed values to match what was actually set
      ObjectSetString(0, PFX+"LIV_SLE_"+IntegerToString(row), OBJPROP_TEXT,
                      newSL > 0 ? DoubleToString(newSL, digits) : "");
      ObjectSetString(0, PFX+"LIV_TPE_"+IntegerToString(row), OBJPROP_TEXT,
                      newTP > 0 ? DoubleToString(newTP, digits) : "");
   }
   else
   {
      uint rc = trade.ResultRetcode();
      AddHistory("Live Set FAIL #" + IntegerToString((int)t) +
                 " in='" + slStr + "/" + tpStr + "'" +
                 " SL=" + DoubleToString(newSL,digits) +
                 " TP=" + DoubleToString(newTP,digits) +
                 " rc=" + IntegerToString((int)rc));
   }
}

//+------------------------------------------------------------------+
//|  LOT / BE/TRADE ADJUSTERS                                         |
//+------------------------------------------------------------------+
void ChangeLot(double delta)
{
   string sym = EffectiveSymbol();
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double minV = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double maxV = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;
   if(minV <= 0) minV = 0.01;
   if(maxV <= 0) maxV = 100.0;
   double v = g_lotSize + delta;
   v = NormalizeDouble(MathRound(v / step) * step, 2);
   if(v < minV) v = minV;
   if(v > maxV) v = maxV;
   g_lotSize = v;
   UpdateLotDisplay();
   SaveLot();
}
void ChangeBePer(double delta)
{
   double v = NormalizeDouble(g_bePerOffset + delta, 2);
   if(v < 0.01) v = 0.01;
   g_bePerOffset = v;
   UpdateBeDisplay();
   SaveBePer();
}

//+------------------------------------------------------------------+
//|  MARKET ORDERS                                                    |
//+------------------------------------------------------------------+
int ExecMarketBuy()
{
   string sym = EffectiveSymbol();
   double price = SymbolInfoDouble(sym, SYMBOL_ASK);
   if(trade.Buy(g_lotSize, sym, price, 0, 0, "Nexal"))
   { AddHistory("BUY " + DoubleToString(g_lotSize,2) + " " + sym); return 1; }
   Print("BUY failed: ", trade.ResultRetcode());
   return 0;
}
int ExecMarketSell()
{
   string sym = EffectiveSymbol();
   double price = SymbolInfoDouble(sym, SYMBOL_BID);
   if(trade.Sell(g_lotSize, sym, price, 0, 0, "Nexal"))
   { AddHistory("SELL " + DoubleToString(g_lotSize,2) + " " + sym); return 1; }
   Print("SELL failed: ", trade.ResultRetcode());
   return 0;
}

//+------------------------------------------------------------------+
int OnInit()
{
   g_chartSym  = _Symbol;
   g_targetSym = (InpSymbol == "" ? _Symbol : InpSymbol);
   if(!SymbolSelect(g_targetSym, true)) g_targetSym = _Symbol;

   g_panelX = InpAnchorX;
   g_panelY = InpAnchorY;
   LoadPanelPos();
   LoadLot();
   LoadBePer();
   LoadCollapseState();
   if(g_bulkSym == "") g_bulkSym = g_chartSym;
   ArrayResize(g_activeTickets, 0);
   ArrayResize(g_history, 0);
   ArrayResize(g_liveTickets, InpLiveRows);
   ArrayResize(g_liveTicketsCache, InpLiveRows);
   for(int i = 0; i < InpLiveRows; i++) g_liveTicketsCache[i] = 0;

   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(g_targetSym);
   if(InpMagic >= 0) trade.SetExpertMagicNumber(InpMagic);

   RecalcBtnW();
   ObjectsDeleteAll(0, PFX);
   CreateAll();
   SwitchTab(TAB_TRADING);
   UpdateInfoRow();
   UpdatePriceDisplay();
   UpdateLotDisplay();
   UpdateBeDisplay();
   UpdateSymbolDisplay();
   RefreshButtonStates();
   UpdateStatus();

   ChartSetInteger(0, CHART_EVENT_MOUSE_MOVE, true);
   ChartSetInteger(0, CHART_EVENT_MOUSE_WHEEL, true);
   if(InpDisableChartDrag) ChartSetInteger(0, CHART_MOUSE_SCROLL, false);
   EventSetTimer(1);

   Print("Nexal Trade Panel v6.91 active | Target=", g_targetSym);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   CloseSymDropdown();
   SavePanelPos();
   SaveLot();
   SaveBePer();
   SaveCollapseState();
   ChartSetInteger(0, CHART_EVENT_MOUSE_MOVE, false);
   ChartSetInteger(0, CHART_MOUSE_SCROLL, true);
   ObjectsDeleteAll(0, PFX);
   ChartRedraw();
}

void OnTick()
{
   UpdatePriceDisplay();
   if(g_activeMode != "" && CountLivingActiveTickets() == 0)
   {
      // All snapshot trades closed — auto-end the active mode
      if(g_activeHistIdx >= 0) MarkHistoryDone(g_activeHistIdx);
      AddHistory(ModeLabel(g_activeMode) + " auto-stopped (all trades closed)");
      g_activeMode = "";
      g_activeHistIdx = -1;
      ArrayResize(g_activeTickets, 0);
      RefreshButtonStates();
      UpdateStatus();
   }
   ApplyActiveMode();
   if(g_activeMode != "") UpdateStatus();
   if(g_currentTab == TAB_LIVE) UpdateLiveTrades();
   if(g_currentTab == TAB_ACC)  UpdateAccount();
}

void OnTimer()
{
   UpdateDot();
   if(g_currentTab == TAB_LIVE) UpdateLiveTrades();
   if(g_currentTab == TAB_ACC)  UpdateAccount();
}

//+------------------------------------------------------------------+
bool IsOverHeader(int mx, int my)
{
   int hx0 = g_panelX + InpFramePad;
   int hy0 = g_panelY + InpFramePad;
   int headerH = 36;
   int innerW = InnerW();
   if(my < hy0 || my > hy0 + headerH) return false;
   if(mx < hx0 || mx > hx0 + innerW) return false;
   int tabsX0 = hx0 + innerW - 242;
   int tabsX1 = hx0 + innerW - 26;
   if(mx >= tabsX0 && mx <= tabsX1) return false;
   return true;
}
void ConstrainToChart(int &x, int &y)
{
   int cw = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int ch = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int pw = (int)ObjectGetInteger(0, PFX+"FRAME", OBJPROP_XSIZE);
   int ph = (int)ObjectGetInteger(0, PFX+"FRAME", OBJPROP_YSIZE);
   if(pw <= 0) pw = FullW();
   if(ph <= 0) ph = FullH();
   if(x < 0) x = 0;
   if(y < 0) y = 0;
   if(x + pw > cw) x = cw - pw;
   if(y + ph > ch) y = ch - ph;
}
void HandleMouseMove(int mx, int my, const string &flags)
{
   g_lastMouseX = mx;
   g_lastMouseY = my;
   int state = (int)StringToInteger(flags);
   bool down = (state & 1) != 0;
   if(down && !g_leftWasDown)
   {
      if(IsOverHeader(mx, my))
      { g_isDragging = true; g_dragGrabX = mx - g_panelX; g_dragGrabY = my - g_panelY;
        if(g_symDropdownOpen) CloseSymDropdown();
        if(g_bulkDropdownOpen) CloseBulkDropdown(); }
   }
   else if(!down && g_leftWasDown)
   { if(g_isDragging) { g_isDragging = false; SavePanelPos(); } }
   else if(down && g_isDragging)
   {
      int nx = mx - g_dragGrabX, ny = my - g_dragGrabY;
      ConstrainToChart(nx, ny);
      if(nx != g_panelX || ny != g_panelY)
      {
         g_panelX = nx; g_panelY = ny;
         if(g_currentTab == TAB_TRADING)      LayoutTrading();
         else if(g_currentTab == TAB_HISTORY) LayoutHistory();
         else if(g_currentTab == TAB_HELP)    LayoutHelp();
         else if(g_currentTab == TAB_ACCOUNT) LayoutAccount();
         else                                  LayoutLive();
      }
   }
   g_leftWasDown = down;
}

//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   if(id == CHARTEVENT_CHART_CHANGE)
   {
      g_chartSym = _Symbol;
      UpdateInfoRow();
      int prevW = g_btnW;
      RecalcBtnW();
      if(g_btnW != prevW) SwitchTab(g_currentTab);
      return;
   }
   if(id == CHARTEVENT_MOUSE_MOVE)
   { HandleMouseMove((int)lparam, (int)dparam, sparam); return; }
   if(id == CHARTEVENT_MOUSE_WHEEL)
   {
      // upper word of lparam contains the wheel delta (signed)
      int delta = (int)((lparam >> 16) & 0xFFFF);
      if(delta > 32767) delta -= 65536;
      if(delta == 0) return;
      // only react if cursor is over the panel
      int pw = (int)ObjectGetInteger(0, PFX+"FRAME", OBJPROP_XSIZE);
      int ph = (int)ObjectGetInteger(0, PFX+"FRAME", OBJPROP_YSIZE);
      if(pw <= 0) pw = FullW();
      if(ph <= 0) ph = FullH();
      bool over = (g_lastMouseX >= g_panelX && g_lastMouseX <= g_panelX + pw &&
                   g_lastMouseY >= g_panelY && g_lastMouseY <= g_panelY + ph);
      if(!over) return;
      // wheel up (positive) = scroll TOWARDS newer/top = decrease offset
      // wheel down (negative) = scroll TOWARDS older/bottom = increase offset
      int step = (delta > 0) ? -1 : 1;
      if(g_currentTab == TAB_HISTORY)
      {
         g_histScrollOffset += step;
         if(g_histScrollOffset < 0) g_histScrollOffset = 0;
         int maxOff = MathMax(0, ArraySize(g_history) - InpHistoryRows);
         if(g_histScrollOffset > maxOff) g_histScrollOffset = maxOff;
         RenderHistory();
         return;
      }
      if(g_currentTab == TAB_LIVE)
      {
         g_liveScrollOffset += step;
         if(g_liveScrollOffset < 0) g_liveScrollOffset = 0;
         ulong tmp[]; int total = CollectAllTickets(tmp);
         int maxOff = MathMax(0, total - InpLiveRows);
         if(g_liveScrollOffset > maxOff) g_liveScrollOffset = maxOff;
         UpdateLiveTrades();
         return;
      }
      return;
   }
   if(id != CHARTEVENT_OBJECT_CLICK) return;
   if(StringFind(sparam, PFX) != 0) return;
   ObjectSetInteger(0, sparam, OBJPROP_STATE, false);

   string key = StringSubstr(sparam, StringLen(PFX));

   //--- Dropdown
   if(key == "DD_ALL")
   {
      g_targetSym = "ALL";
      UpdateSymbolDisplay();
      UpdateInfoRow();
      UpdateLotDisplay();
      UpdateBeDisplay();
      CloseSymDropdown();
      return;
   }
   if(StringFind(key, "DD_") == 0)
   {
      int idx = (int)StringToInteger(StringSubstr(key, 3));
      if(idx >= 0 && idx < SymbolsTotal(true))
      {
         g_targetSym = SymbolName(idx, true);
         SymbolSelect(g_targetSym, true);
         UpdateSymbolDisplay();
         UpdateInfoRow();
         LoadLot();
         LoadBePer();
         UpdateLotDisplay();
         UpdateBeDisplay();
      }
      CloseSymDropdown();
      return;
   }
   if(key == "INFO_TGT" || key == "SYM_DISP" || key == "SYM_LBL")
   {
      if(g_symDropdownOpen) CloseSymDropdown();
      else OpenSymDropdown();
      return;
   }
   if(g_symDropdownOpen) CloseSymDropdown();

   //--- Tabs
   if(key == "TAB_TRD") { SwitchTab(TAB_TRADING); return; }
   if(key == "TAB_HIS") { SwitchTab(TAB_HISTORY); return; }
   if(key == "TAB_LIV") { SwitchTab(TAB_LIVE);    return; }
   if(key == "TAB_ACC") { SwitchTab(TAB_ACCOUNT); return; }
   if(key == "TAB_HLP") { SwitchTab(TAB_HELP);    return; }
   if(key == "TITLE" || key == "DOT" || key == "DRAG" || key == "HEADER_BG") return;
   if(key == "INFO_CHART" || key == "INFO_TF") return;
   if(key == "FOOTER_VER") return;

   //--- Scroll buttons (HIST and LIVE tabs)
   if(key == "HIS_UP")
   {
      g_histScrollOffset--;
      if(g_histScrollOffset < 0) g_histScrollOffset = 0;
      RenderHistory();
      return;
   }
   if(key == "HIS_DN")
   {
      int maxOff = MathMax(0, ArraySize(g_history) - InpHistoryRows);
      g_histScrollOffset++;
      if(g_histScrollOffset > maxOff) g_histScrollOffset = maxOff;
      RenderHistory();
      return;
   }
   if(key == "LIV_UP")
   {
      g_liveScrollOffset--;
      if(g_liveScrollOffset < 0) g_liveScrollOffset = 0;
      UpdateLiveTrades();
      return;
   }
   if(key == "LIV_DN")
   {
      ulong tmp[]; int total = CollectAllTickets(tmp);
      int maxOff = MathMax(0, total - InpLiveRows);
      g_liveScrollOffset++;
      if(g_liveScrollOffset > maxOff) g_liveScrollOffset = maxOff;
      UpdateLiveTrades();
      return;
   }
   if(key == "HIS_HDR" || key == "LIV_HDR") return;
   //--- Section collapse toggles (only on Trading tab; STATUS section not collapsible)
   if(g_currentTab == TAB_TRADING)
   {
      if(key == "SEC_TRD") { g_collapsedTrade = !g_collapsedTrade; SaveCollapseState(); LayoutTrading(); return; }
      if(key == "SEC_ORD") { g_collapsedOrder = !g_collapsedOrder; SaveCollapseState(); LayoutTrading(); return; }
      if(key == "SEC_MGM") { g_collapsedMgm   = !g_collapsedMgm;   SaveCollapseState(); LayoutTrading(); return; }
      if(key == "SEC_CLS") { g_collapsedClose = !g_collapsedClose; SaveCollapseState(); LayoutTrading(); return; }
   }
   if(StringFind(key, "SEC_") == 0)  return;
   if(StringFind(key, "PRICE_") == 0) return;
   if(key == "LOT_DISP" || key == "BEPT_DISP") return;
   if(StringFind(key, "HLP_T_") == 0 || StringFind(key, "HLP_D_") == 0) return;
   //--- Bulk Dropdown
   if(StringFind(key, "BULK_DD_") == 0)
   {
      int idx = (int)StringToInteger(StringSubstr(key, 8));
      if(idx >= 0 && idx < SymbolsTotal(true))
      {
         g_bulkSym = SymbolName(idx, true);
         SymbolSelect(g_bulkSym, true);
         SetText(PFX+"BULK_SYM_DISP", g_bulkSym);
      }
      CloseBulkDropdown();
      return;
   }
   if(key == "BULK_HDR" || key == "BULK_SYM_DISP")
   {
      if(g_bulkDropdownOpen) CloseBulkDropdown();
      else OpenBulkDropdown();
      return;
   }
   if(g_bulkDropdownOpen) CloseBulkDropdown();

   if(key == "BULK_SLL" || key == "BULK_TPL") return;
   if(key == "BULK_SLE" || key == "BULK_TPE") return;
   if(key == "BULK_S") { LiveBulkSet(); UpdateLiveTrades(); return; }
   if(key == "BULK_DIV") return;

   if(StringFind(key, "LIV_INFO_") == 0) return;
   if(StringFind(key, "LIV_SLE_")  == 0) return;
   if(StringFind(key, "LIV_TPE_")  == 0) return;
   if(StringFind(key, "LIV_SLL_")  == 0) return;
   if(StringFind(key, "LIV_TPL_")  == 0) return;
   if(StringFind(key, "HIS_T_") == 0 || StringFind(key, "HIS_A_") == 0 ||
      StringFind(key, "HIS_S_") == 0) return;

   //--- History stop
   if(StringFind(key, "HIS_X_") == 0)
   {
      int rowIdx = (int)StringToInteger(StringSubstr(key, 6));
      int total = ArraySize(g_history);
      int histIdx = total - 1 - rowIdx;
      if(histIdx >= 0 && histIdx < total && g_history[histIdx].active)
      {
         if(histIdx == g_activeHistIdx) StopActiveMode();
         else MarkHistoryDone(histIdx);
      }
      return;
   }

   //--- LIVE per-trade
   if(StringFind(key, "LIV_C_") == 0)
   { int r = (int)StringToInteger(StringSubstr(key, 6)); LiveClose(r); UpdateLiveTrades(); return; }
   if(StringFind(key, "LIV_H_") == 0)
   { int r = (int)StringToInteger(StringSubstr(key, 6)); LiveHalf(r);  UpdateLiveTrades(); return; }
   if(StringFind(key, "LIV_B_") == 0)
   { int r = (int)StringToInteger(StringSubstr(key, 6)); LiveBe(r);    UpdateLiveTrades(); return; }
   if(StringFind(key, "LIV_S_") == 0)
   { int r = (int)StringToInteger(StringSubstr(key, 6)); LiveSet(r);   UpdateLiveTrades(); return; }

   //--- Lot
   if(key == "LOT_MM") { ChangeLot(-0.10); return; }
   if(key == "LOT_M")  { ChangeLot(-0.01); return; }
   if(key == "LOT_P")  { ChangeLot(+0.01); return; }
   if(key == "LOT_PP") { ChangeLot(+0.10); return; }

   //--- BE All ONE-SHOT presets (12 values)
   if(key == "BEALL_036")  { ApplyBeWorstOnce(0.36);  return; }
   if(key == "BEALL_050")  { ApplyBeWorstOnce(0.50);  return; }
   if(key == "BEALL_100")  { ApplyBeWorstOnce(1.00);  return; }
   if(key == "BEALL_200")  { ApplyBeWorstOnce(2.00);  return; }
   if(key == "BEALL_300")  { ApplyBeWorstOnce(3.00);  return; }
   if(key == "BEALL_400")  { ApplyBeWorstOnce(4.00);  return; }
   if(key == "BEALL_500")  { ApplyBeWorstOnce(5.00);  return; }
   if(key == "BEALL_600")  { ApplyBeWorstOnce(6.00);  return; }
   if(key == "BEALL_700")  { ApplyBeWorstOnce(7.00);  return; }
   if(key == "BEALL_800")  { ApplyBeWorstOnce(8.00);  return; }
   if(key == "BEALL_900")  { ApplyBeWorstOnce(9.00);  return; }
   if(key == "BEALL_1000") { ApplyBeWorstOnce(10.00); return; }

   //--- BE/Trade ONE-SHOT
   if(key == "BEPT_MM") { ChangeBePer(-1.00); return; }
   if(key == "BEPT_M")  { ChangeBePer(-0.50); return; }
   if(key == "BEPT_P")  { ChangeBePer(+0.50); return; }
   if(key == "BEPT_PP") { ChangeBePer(+1.00); return; }
   if(key == "BEPT_GO") { ApplyBePerTradeOnce(g_bePerOffset); return; }

   if(key == "STOP") { StopActiveMode(); return; }

   if(key == "MKT_BUY")  { ExecMarketBuy();  return; }
   if(key == "MKT_SELL") { ExecMarketSell(); return; }

   //--- Trails (still modes)
   if(key == "TRL_FAST") { SetActiveMode("TRL_FAST"); return; }
   if(key == "TRL_MED")  { SetActiveMode("TRL_MED"); return; }
   if(key == "TRL_SLOW") { SetActiveMode("TRL_SLOW"); return; }

   //--- Close buttons
   if(key == "CLS_25")   { CloseByPercent(0.25); return; }
   if(key == "CLS_50")   { CloseByPercent(0.50); return; }
   if(key == "CLS_75")   { CloseByPercent(0.75); return; }
   if(key == "CLS_BUY")  { ClosePositionsFast(POSITION_TYPE_BUY, false); return; }
   if(key == "CLS_SELL") { ClosePositionsFast(POSITION_TYPE_SELL,false); return; }
   if(key == "CLS_ALL")  { ClosePositionsFast(POSITION_TYPE_BUY, true);  return; }
   if(key == "CLS_PRF")  { CloseByProfitStatus(true);  return; }
   if(key == "CLS_LSS")  { CloseByProfitStatus(false); return; }

   if(key == "CLS_50BE") { ClosePercentThenBE(0.50); return; }
   if(key == "CLS_75BE") { ClosePercentThenBE(0.75); return; }
   if(key == "CLS_80BE") { ClosePercentThenBE(0.80); return; }
}
//+------------------------------------------------------------------+
