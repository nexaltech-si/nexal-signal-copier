from loguru import logger

from src.models import TradingSignal, RiskAssessment, AccountInfo, SignalType
from config import settings
from src.integrations.trading.provider_factory import create_trading_provider


class RiskManager:
    """Advanced risk management system for trading signals"""
    
    def __init__(self):
        self._trading_provider = None  # Lazy initialization
        self.open_positions_count = 0
        self._pip_estimated: dict = {}  # symbol -> True if the LAST pip value used was a hardcoded guess
    
    @property
    def trading_provider(self):
        """Lazy initialization of trading provider"""
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider
        
    async def assess_risk(
        self,
        signal: TradingSignal,
        account_info: AccountInfo
    ) -> RiskAssessment:
        """
        Assess risk for a trading signal and calculate position size
        
        Returns:
            RiskAssessment with approval status and calculated lot size
        """
        logger.info(f"📊 Starting risk assessment for {signal.signal_type} {signal.symbol}")
        logger.debug(f"   Account Balance: ${account_info.balance:.2f}")
        logger.debug(f"   Entry: {signal.entry_price}, SL: {signal.stop_loss}, TP: {signal.take_profit}")
        
        warnings = []

        # Check maximum open positions
        if not self._check_max_positions(account_info):
            return RiskAssessment(
                approved=False,
                calculated_lot_size=0.0,
                risk_amount=0.0,
                risk_percent=0.0,
                stop_loss_pips=0.0,
                take_profit_pips=0.0,
                risk_reward_ratio=0.0,
                reason="Maximum open positions reached",
                warnings=warnings
            )
        
        # Get entry and stop loss
        entry_price = signal.entry_price
        stop_loss = signal.stop_loss
        take_profit = signal.take_profit

        # Track whether a specific entry level was provided by the signal.
        # Entry-spread adjustment only applies to explicit entry levels
        # (single price or a range), not to market-derived entries.
        entry_explicit = signal.entry_price is not None
        has_full_range = bool(signal.entry_range_min and signal.entry_range_max)

        # Shift the whole entry range for spread (same direction as the single-entry
        # adjustment: BUY up, SELL down) BEFORE deriving the midpoint, so both the
        # risk calc and the provider's per-order distribution use the shifted range.
        if has_full_range:
            original_min, original_max = signal.entry_range_min, signal.entry_range_max
            adjustment = await self._get_spread_adjustment(signal)
            if adjustment:
                delta = adjustment if self._is_buy_signal(signal) else -adjustment
                signal.entry_range_min = round(signal.entry_range_min + delta, 5)
                signal.entry_range_max = round(signal.entry_range_max + delta, 5)
                warnings.append(
                    f"Entry range adjusted for spread: "
                    f"{original_min}–{original_max} → {signal.entry_range_min}–{signal.entry_range_max}"
                )
                logger.info(
                    f"📊 Entry range adjusted for spread: "
                    f"{original_min}–{original_max} → {signal.entry_range_min}–{signal.entry_range_max}"
                )

        # For range entries, use the midpoint as the effective entry for risk calc
        if not entry_price and signal.entry_range_min and signal.entry_range_max:
            entry_price = (signal.entry_range_min + signal.entry_range_max) / 2
            logger.info(
                f"📊 Range entry: using midpoint {entry_price:.5f} "
                f"(range {signal.entry_range_min} – {signal.entry_range_max})"
            )
            warnings.append(
                f"Range entry: using midpoint {entry_price:.5f} "
                f"({signal.entry_range_min} – {signal.entry_range_max})"
            )
        elif not entry_price and (signal.entry_range_min or signal.entry_range_max):
            entry_price = signal.entry_range_min or signal.entry_range_max
            logger.warning(f"⚠️ Partial range: using single bound {entry_price:.5f}")
            warnings.append(f"Partial range entry: using single bound {entry_price:.5f}")

        # Fetch current market price if entry price is still missing
        if not entry_price:
            try:
                entry_price = await self._fetch_current_price(signal.symbol, signal.signal_type)
                warnings.append(f"No entry price specified, using market price: {entry_price}")
                logger.info(f"💰 Fetched market price for risk calculation: {entry_price}")
            except Exception as e:
                error_msg = str(e)
                if "No price data available" in error_msg or "market may be closed" in error_msg:
                    logger.error(f"🚨 Cannot fetch price for {signal.symbol}: {e}")
                    return RiskAssessment(
                        approved=False,
                        calculated_lot_size=0.0,
                        risk_amount=0.0,
                        risk_percent=0.0,
                        stop_loss_pips=0.0,
                        take_profit_pips=0.0,
                        risk_reward_ratio=0.0,
                        reason=f"No price data available for {signal.symbol} - market may be closed or symbol not actively trading",
                        warnings=[f"Cannot fetch current price for {signal.symbol}"]
                    )
                logger.warning(f"⚠️ Could not fetch market price: {e}")
                warnings.append("Could not fetch market price for risk calculation")

        # Adjust entry level for spread (opposite direction of the SL adjustment).
        # BUY: move entry UP by spread × multiplier; SELL: move entry DOWN.
        # Only applies when a specific entry level was given (pending/limit/stop).
        #
        # Multi-entry (scale-in) signals place one order per leg in signal.entries,
        # NOT off signal.entry_price — so the shift must be applied to EVERY leg,
        # the same way the range branch above shifts entry_range_min/max. Adjusting
        # only entry_price here would leave the placed legs at their raw prices.
        discrete_legs = (
            signal.discrete_entry_prices()
            if hasattr(signal, 'discrete_entry_prices') else None
        )
        if discrete_legs:
            adjustment = await self._get_spread_adjustment(signal)
            if adjustment:
                delta = adjustment if self._is_buy_signal(signal) else -adjustment
                original_legs = list(signal.entries)
                signal.entries = [round(float(e) + delta, 5) for e in signal.entries]
                # Keep entry_price (legacy mirror / sizing seed) in sync with the
                # first shifted leg and re-point the local entry_price used below.
                entry_price = signal.entries[0]
                signal.entry_price = entry_price
                warnings.append(
                    f"Entry legs adjusted for spread: {original_legs} → {signal.entries}"
                )
                logger.info(
                    f"📊 Entry legs adjusted for spread: {original_legs} → {signal.entries}"
                )
        elif entry_explicit and entry_price:
            original_entry = entry_price
            entry_price = await self._adjust_entry_for_spread(signal, entry_price)
            if entry_price != original_entry:
                warnings.append(f"Entry adjusted for spread: {original_entry} → {entry_price}")
                logger.info(f"📊 Entry adjusted for spread: {original_entry:.5f} → {entry_price:.5f}")
                # Write back so execution places the order at the adjusted entry
                signal.entry_price = entry_price

        # Calculate stop loss if not provided (60 pips default)
        if not stop_loss and entry_price:
            stop_loss = await self._calculate_default_stop_loss(
                signal,
                entry_price,
                signal.symbol
            )
            warnings.append(f"Auto-calculated stop loss (60 pips): {stop_loss}")
            logger.info(f"🛑 Auto-calculated SL: {stop_loss}")
            # Update signal object with calculated SL
            signal.stop_loss = stop_loss
        
        # Validate SL is on correct side of entry price
        if stop_loss and entry_price:
            from src.models import OrderType
            is_buy = False
            if signal.order_type:
                is_buy = (signal.order_type == OrderType.BUY)
            elif signal.signal_type:
                is_buy = signal.signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]
            
            if is_buy and stop_loss >= entry_price:
                error_msg = f"Invalid SL for BUY order: SL ({stop_loss}) must be below entry ({entry_price})"
                logger.error(f"🚨 {error_msg}")
                return RiskAssessment(
                    approved=False,
                    calculated_lot_size=0.0,
                    risk_amount=0.0,
                    risk_percent=0.0,
                    stop_loss_pips=0.0,
                    take_profit_pips=0.0,
                    risk_reward_ratio=0.0,
                    reason=error_msg,
                    warnings=warnings
                )
            elif not is_buy and stop_loss <= entry_price:
                error_msg = f"Invalid SL for SELL order: SL ({stop_loss}) must be above entry ({entry_price})"
                logger.error(f"🚨 {error_msg}")
                return RiskAssessment(
                    approved=False,
                    calculated_lot_size=0.0,
                    risk_amount=0.0,
                    risk_percent=0.0,
                    stop_loss_pips=0.0,
                    take_profit_pips=0.0,
                    risk_reward_ratio=0.0,
                    reason=error_msg,
                    warnings=warnings
                )
        
        # Adjust stop loss for spread to avoid immediate closure
        if stop_loss and entry_price:
            original_sl = stop_loss
            stop_loss = await self._adjust_stop_loss_for_spread(
                signal,
                entry_price,
                stop_loss
            )
            if stop_loss != original_sl:
                warnings.append(f"Stop loss adjusted for spread: {original_sl} → {stop_loss}")
                logger.info(f"📊 SL adjusted for spread: {original_sl:.5f} → {stop_loss:.5f}")
                # Update signal object with adjusted SL
                signal.stop_loss = stop_loss

        # MULTI-ENTRY (scale-in): the total lot is split across legs at execution, so
        # size the WHOLE position off the leg FURTHEST from SL (widest per-lot risk).
        # This guarantees aggregate risk across the split legs never exceeds the target
        # — the "split total risk" policy — rather than secretly multiplying it.
        legs = signal.discrete_entry_prices() if hasattr(signal, 'discrete_entry_prices') else None
        if legs and stop_loss:
            worst_leg = max(legs, key=lambda lg: abs(lg - stop_loss))
            if worst_leg != entry_price:
                logger.info(
                    f"🪜 Multi-entry sizing: using widest-risk leg {worst_leg} of {legs} "
                    f"(SL {stop_loss}) so split legs stay within target risk"
                )
                warnings.append(
                    f"Scale-in ({len(legs)} legs {legs}): sized off widest-risk leg {worst_leg}; "
                    f"total risk split across legs"
                )
                entry_price = worst_leg

        if not take_profit and entry_price and stop_loss:
            # Auto-generate multi-TP levels since signal has none
            from src.models import OrderType
            is_buy = False
            if signal.order_type:
                is_buy = (signal.order_type == OrderType.BUY)
            elif signal.signal_type:
                is_buy = signal.signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]
            
            sl_distance = abs(entry_price - stop_loss)
            
            if settings.auto_tp_calculation_method == "RR":
                # Generate 3 TP levels at 1×, 1.5×, and 2× RR
                rr = settings.auto_tp_risk_reward
                tp_multipliers = [rr * 0.5, rr * 0.75, rr]  # e.g., 1.0, 1.5, 2.0 for RR=2.0
                
                if is_buy:
                    take_profit = [round(entry_price + (sl_distance * m), 5) for m in tp_multipliers]
                else:
                    take_profit = [round(entry_price - (sl_distance * m), 5) for m in tp_multipliers]
            else:
                # PIPS method — generate 3 TP levels
                pip_multiplier = await self._get_pip_multiplier(signal.symbol)
                pip_size = 1 / pip_multiplier
                base_pips = settings.auto_tp_pips
                tp_pips = [base_pips * 0.5, base_pips * 0.75, base_pips]
                
                if is_buy:
                    take_profit = [round(entry_price + (p * pip_size), 5) for p in tp_pips]
                else:
                    take_profit = [round(entry_price - (p * pip_size), 5) for p in tp_pips]

            if getattr(signal, 'temp_stop_loss', False):
                # Instant entry on a temporary SL: ONE position on the furthest level.
                # The follow-up brings the real TPs; three orders on guessed levels
                # were too much for a message that has no SL yet.
                take_profit = take_profit[-1:]

            # Write back to signal so execution uses these TPs
            signal.take_profit = take_profit
            logger.info(f"🎯 Auto-generated {len(take_profit)} TP levels: {take_profit}")
            logger.info(f"   Method: {settings.auto_tp_calculation_method}, Direction: {'BUY' if is_buy else 'SELL'}")
            warnings.append(f"Auto-generated {len(take_profit)} TP levels: {take_profit}")
        
        # CRITICAL SAFETY CHECK: Never trade without stop loss
        if not stop_loss:
            logger.error("🚨 CRITICAL: Cannot execute trade without stop loss!")
            return RiskAssessment(
                approved=False,
                calculated_lot_size=0.0,
                risk_amount=0.0,
                risk_percent=0.0,
                stop_loss_pips=0.0,
                take_profit_pips=0.0,
                risk_reward_ratio=0.0,
                reason="REJECTED: Stop loss is mandatory for all trades",
                warnings=warnings + ["Stop loss could not be determined - trade blocked for safety"]
            )
        
        # Calculate pip values
        stop_loss_pips = 0.0
        take_profit_pips = 0.0
        risk_reward_ratio = 0.0
        
        if entry_price and stop_loss:
            pip_multiplier = await self._get_pip_multiplier(signal.symbol)
            stop_loss_pips = abs(entry_price - stop_loss) * pip_multiplier
            
            if take_profit:
                # Handle multi-TP signals: use first TP level for R:R calculation
                tp_for_calculation = take_profit[0] if isinstance(take_profit, list) else take_profit
                take_profit_pips = abs(tp_for_calculation - entry_price) * pip_multiplier
                risk_reward_ratio = take_profit_pips / stop_loss_pips if stop_loss_pips > 0 else 0
                
                if isinstance(take_profit, list):
                    logger.info(f"📊 Multi-TP detected: Using first TP {tp_for_calculation} for R:R calculation (Total TPs: {len(take_profit)})")
        
        # Check risk-reward ratio
        if risk_reward_ratio > 0 and risk_reward_ratio < 1.0:
            warnings.append(f"Low risk-reward ratio: {risk_reward_ratio:.2f}")
        
        # Calculate position size
        logger.info("📊 LOT SIZE CALCULATION DEBUG:")
        logger.info(f"   Account Balance: ${account_info.balance:.2f}")
        logger.info(f"   Risk Percent: {settings.max_risk_per_trade_percent}%")
        logger.info(f"   Stop Loss Pips: {stop_loss_pips:.1f}")
        logger.info(f"   Symbol: {signal.symbol}")
        
        lot_size = await self._calculate_position_size(
            account_balance=account_info.balance,
            risk_percent=settings.max_risk_per_trade_percent,
            stop_loss_pips=stop_loss_pips,
            symbol=signal.symbol
        )
        
        logger.info(f"   Calculated Lot Size: {lot_size}")
        logger.info(f"   Min/Max Limits: {settings.min_lot_size} / {settings.max_lot_size}")
        
        # Override with signal lot size if specified and within limits
        # BUT ONLY if it doesn't exceed risk limits
        if signal.lot_size:
            if settings.min_lot_size <= signal.lot_size <= settings.max_lot_size:
                # Validate that this lot size doesn't exceed risk limits
                test_risk_amount = await self._calculate_risk_amount(
                    lot_size=signal.lot_size,
                    stop_loss_pips=stop_loss_pips,
                    symbol=signal.symbol
                )
                test_risk_percent = (test_risk_amount / account_info.balance) * 100 if account_info.balance > 0 else 0
                
                # Only use signal's lot size if it's within acceptable risk
                if round(test_risk_percent, 2) <= (settings.max_risk_per_trade_percent + 0.05):
                    lot_size = signal.lot_size
                    warnings.append(f"Using signal-specified lot size: {lot_size}")
                    logger.info(f"✅ Validated signal lot size {lot_size} (risk: {test_risk_percent:.2f}%)")
                else:
                    warnings.append(f"Signal lot size {signal.lot_size} would risk {test_risk_percent:.2f}% (exceeds max {settings.max_risk_per_trade_percent}%), using calculated: {lot_size}")
                    logger.warning(f"⚠️ Signal lot size {signal.lot_size} rejected: would risk {test_risk_percent:.2f}% > {settings.max_risk_per_trade_percent}%")
            else:
                warnings.append(f"Signal lot size {signal.lot_size} out of range, using calculated: {lot_size}")
        
        # Fetch broker's volume step for proper rounding
        try:
            spec = await self.trading_provider.get_symbol_specification(signal.symbol)
            volume_step = spec.get('volumeStep', 0.01)
            volume_min = max(spec.get('volumeMin', settings.min_lot_size), settings.min_lot_size)
        except Exception as e:
            error_msg = str(e)
            if "Cannot get symbol specification" in error_msg or "NOT FOUND" in error_msg:
                logger.error(f"🚨 Symbol {signal.symbol} not available for trading: {e}")
                return RiskAssessment(
                    approved=False,
                    calculated_lot_size=0.0,
                    risk_amount=0.0,
                    risk_percent=0.0,
                    stop_loss_pips=0.0,
                    take_profit_pips=0.0,
                    risk_reward_ratio=0.0,
                    reason=f"Symbol {signal.symbol} is not available on this broker. Cannot execute trade.",
                    warnings=[f"Symbol {signal.symbol} not found in broker's symbol list"]
                )
            volume_step = 0.01
            volume_min = settings.min_lot_size
        
        # Round the lot size using broker's volume step
        try:
            rounded_lot_size = await self.trading_provider.round_lot_size(signal.symbol, lot_size)
        except Exception as e:
            error_msg = str(e)
            if "Cannot determine valid lot size" in error_msg or "Cannot get symbol specification" in error_msg or "NOT FOUND" in error_msg:
                logger.error(f"🚨 Symbol {signal.symbol} not available for trading: {e}")
                return RiskAssessment(
                    approved=False,
                    calculated_lot_size=0.0,
                    risk_amount=0.0,
                    risk_percent=0.0,
                    stop_loss_pips=0.0,
                    take_profit_pips=0.0,
                    risk_reward_ratio=0.0,
                    reason=f"Symbol {signal.symbol} is not available on this broker. Cannot execute trade.",
                    warnings=[f"Symbol {signal.symbol} not found in broker's symbol list"]
                )
            raise
        risk_amount = await self._calculate_risk_amount(
            lot_size=rounded_lot_size,
            stop_loss_pips=stop_loss_pips,
            symbol=signal.symbol
        )
        risk_percent = (risk_amount / account_info.balance) * 100 if account_info.balance > 0 else 0
        
        # If rounding caused risk to exceed limit, iteratively reduce by volume step
        max_risk_threshold = settings.max_risk_per_trade_percent + 0.05
        if round(risk_percent, 2) > max_risk_threshold and rounded_lot_size > volume_min:
            logger.info(f"⚙️ Adjusting lot size: initial {rounded_lot_size} causes {risk_percent:.2f}% risk")
            
            while round(risk_percent, 2) > max_risk_threshold and rounded_lot_size > volume_min:
                rounded_lot_size -= volume_step
                try:
                    rounded_lot_size = await self.trading_provider.round_lot_size(signal.symbol, rounded_lot_size)
                except Exception as e:
                    error_msg = str(e)
                    if "Cannot determine valid lot size" in error_msg or "Cannot get symbol specification" in error_msg or "NOT FOUND" in error_msg:
                        logger.error(f"🚨 Symbol {signal.symbol} not available for trading: {e}")
                        # Break out of loop and use current lot size
                        break
                    raise
                
                if rounded_lot_size < volume_min:
                    rounded_lot_size = volume_min
                    break
                
                risk_amount = await self._calculate_risk_amount(
                    lot_size=rounded_lot_size,
                    stop_loss_pips=stop_loss_pips,
                    symbol=signal.symbol
                )
                risk_percent = (risk_amount / account_info.balance) * 100 if account_info.balance > 0 else 0
            
            logger.info(f"✅ Adjusted lot size to {rounded_lot_size} (risk: {risk_percent:.2f}%)")
            warnings.append(f"Lot size adjusted from {lot_size} to {rounded_lot_size} to meet risk limit")
        
        lot_size = rounded_lot_size
        logger.info(f"💰 Final risk calculation: Lot={lot_size}, SL={stop_loss_pips:.1f} pips, Risk=${risk_amount:.2f} ({risk_percent:.2f}%)")
        
        # Check if risk is within acceptable limits
        approved = True
        reason = None
        risk_limit_exceeded = False

        # FINAL SAFETY CHECK: Verify stop loss is present (double check)
        if not stop_loss or stop_loss_pips <= 0:
            approved = False
            reason = "CRITICAL SAFETY BLOCK: Stop loss missing or invalid"
            logger.error("🚨 Trade blocked: Missing or invalid stop loss")
        elif risk_amount <= 0:
            approved = False
            reason = "CRITICAL SAFETY BLOCK: Risk calculation error (risk_amount = $0)"
            logger.error("🚨 Trade blocked: Risk calculation returned $0 - indicates pip value calculation error")
        elif lot_size < settings.min_lot_size:
            approved = False
            reason = f"Calculated lot size {lot_size} below minimum {settings.min_lot_size}"
        elif lot_size > settings.max_lot_size:
            approved = False
            reason = f"Calculated lot size {lot_size} exceeds maximum {settings.max_lot_size}"
        elif round(risk_percent, 2) > (settings.max_risk_per_trade_percent + 0.05):
            # Round to 2 decimals + 0.05% tolerance for rounding errors
            approved = False
            reason = f"Risk {risk_percent:.2f}% exceeds maximum {settings.max_risk_per_trade_percent}%"
            # SL, lot size and risk amount are all valid here — the trade only
            # fails the risk-percent cap. Flag it so the pipeline can offer a
            # high-risk override (with disclaimer) instead of auto-rejecting.
            risk_limit_exceeded = True
        elif account_info.free_margin < risk_amount * 2:  # Ensure enough margin
            approved = False
            reason = "Insufficient free margin for trade"
        
        sizing_estimated = bool(self._pip_estimated.get(signal.symbol, False))
        if sizing_estimated:
            warnings.append(
                "Lot size uses an ESTIMATED pip value (broker symbol data was unavailable) — verify the lot size before approving"
            )
            logger.warning(f"⚠️ {signal.symbol}: lot size computed from an estimated pip value")

        assessment = RiskAssessment(
            approved=approved,
            calculated_lot_size=round(lot_size, 2),
            risk_amount=round(risk_amount, 2),
            risk_percent=round(risk_percent, 2),
            stop_loss_pips=round(stop_loss_pips, 1),
            take_profit_pips=round(take_profit_pips, 1),
            risk_reward_ratio=round(risk_reward_ratio, 2),
            reason=reason,
            warnings=warnings,
            risk_limit_exceeded=risk_limit_exceeded,
            sizing_estimated=sizing_estimated,
        )
        
        if approved:
            logger.success("✅ Risk assessment passed")
            logger.info(f"   Lot size: {assessment.calculated_lot_size}, Risk: {assessment.risk_percent}%")
            logger.info(f"   R:R = {assessment.risk_reward_ratio}, SL: {assessment.stop_loss_pips} pips")
            logger.info(f"   Stop Loss: {stop_loss:.5f} (VERIFIED PRESENT)")
        else:
            logger.warning(f"❌ Risk assessment failed: {reason}")
        
        return assessment
    
    def _check_max_positions(self, account_info: AccountInfo) -> bool:
        """Check if maximum open positions has been reached"""
        if account_info.open_positions >= settings.max_open_positions:
            logger.warning(f"🛑 Maximum open positions reached: {account_info.open_positions}")
            return False
        
        return True
    
    async def _calculate_position_size(
        self,
        account_balance: float,
        risk_percent: float,
        stop_loss_pips: float,
        symbol: str
    ) -> float:
        """
        Calculate position size based on risk parameters
        
        Formula: Lot Size = (Account Balance * Risk %) / (Stop Loss in Pips * Pip Value)
        Uses broker's symbol specification for volumeMin/volumeMax/volumeStep.
        """
        if stop_loss_pips <= 0:
            logger.error("🚨 Cannot calculate lot size without valid stop loss pips!")
            return 0.0
        
        # Fetch broker's per-symbol limits
        try:
            spec = await self.trading_provider.get_symbol_specification(symbol)
            volume_min = spec.get('volumeMin', settings.min_lot_size)
            volume_max = spec.get('volumeMax', settings.max_lot_size)
            volume_step = spec.get('volumeStep', 0.01)
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch symbol spec for {symbol}, using config defaults: {e}")
            volume_min = settings.min_lot_size
            volume_max = settings.max_lot_size
            volume_step = 0.01
        
        # Apply config limits as an additional safety cap
        effective_min = max(volume_min, settings.min_lot_size)
        effective_max = min(volume_max, settings.max_lot_size)
        
        risk_amount = account_balance * (risk_percent / 100)
        pip_value = await self._get_pip_value(symbol)
        
        logger.debug("💡 Position Size Calculation:")
        logger.debug(f"   Risk Amount: ${risk_amount:.2f}")
        logger.debug(f"   Pip Value: ${pip_value:.2f}/lot")
        logger.debug(f"   Broker limits: min={volume_min}, max={volume_max}, step={volume_step}")
        logger.debug(f"   Formula: {risk_amount:.2f} / ({stop_loss_pips:.1f} × {pip_value:.2f})")
        
        lot_size = risk_amount / (stop_loss_pips * pip_value)
        logger.debug(f"   Raw Lot Size: {lot_size:.4f}")
        
        # Round using broker's volume step
        try:
            lot_size = await self.trading_provider.round_lot_size(symbol, lot_size)
            logger.debug(f"   Rounded Lot Size: {lot_size} (step={volume_step})")
        except Exception as e:
            # Handle case where symbol doesn't exist or is not available
            error_msg = str(e)
            if "Cannot determine valid lot size" in error_msg or "Cannot get symbol specification" in error_msg or "NOT FOUND" in error_msg:
                logger.error(f"🚨 Symbol {symbol} not available for trading: {e}")
                raise Exception(f"Symbol {symbol} is not available on this broker. Cannot execute trade.") from e
            else:
                # Re-raise other errors
                raise
        
        lot_size_before_cap = lot_size
        lot_size = max(effective_min, min(lot_size, effective_max))
        
        if lot_size != lot_size_before_cap:
            logger.warning(f"⚠️ Lot size CAPPED: {lot_size_before_cap} → {lot_size} (limits: {effective_min}-{effective_max})")
        
        return lot_size
    
    async def _calculate_risk_amount(self, lot_size: float, stop_loss_pips: float, symbol: str) -> float:
        """Calculate the risk amount in account currency"""
        pip_value = await self._get_pip_value(symbol)
        return lot_size * stop_loss_pips * pip_value
    
    async def _get_pip_value(self, symbol: str) -> float:
        """
        Get pip value for a symbol dynamically from broker data
        
        CRITICAL: Uses correct pip size based on digits, NOT broker's pipSize
        (broker often returns tick size/points instead of actual pip size)
        
        Pip value formula: pip_size × contract_size
        Example: 0.0001 × 100,000 = $10 per pip for standard forex
        """
        self._pip_estimated[symbol] = False  # set True below only on the hardcoded-guess paths
        try:
            # First, try to get profitTickValue from current price data
            try:
                price_data = await self.trading_provider.get_symbol_price(symbol)
                profit_tick_value = price_data.get('profitTickValue')
                
                if profit_tick_value and profit_tick_value > 0:
                    # Get spec for pip size calculation
                    spec = await self.trading_provider.get_symbol_specification(symbol)
                    tick_size = spec.get('tickSize', 0.00001)
                    digits = spec.get('digits', 5)
                    
                    # Determine correct pip size - CHECK INSTRUMENT TYPE FIRST before digits
                    # This prevents XAUUSD (digits=5) from being caught by standard forex condition,
                    # and ensures JPY pairs are detected by name even when broker reports digits=5.

                    # Gold/XAU - check first!
                    if 'XAU' in symbol.upper() or 'GOLD' in symbol.upper():
                        pip_size = 0.1

                    # Crypto - check second
                    elif 'BTC' in symbol.upper() or 'ETH' in symbol.upper():
                        pip_size = 1.0 if digits <= 2 else 0.1

                    # JPY pairs by name - check before digits (some brokers report digits=5 for JPY)
                    elif 'JPY' in symbol.upper() or 'HUF' in symbol.upper() or 'CZK' in symbol.upper():
                        pip_size = 0.01

                    # JPY-like by digits (fallback for unlisted currencies)
                    elif digits == 3 or digits == 2:
                        pip_size = 0.01

                    # Standard forex pairs
                    elif digits == 5 or digits == 4:
                        pip_size = 0.0001  # Standard forex

                    else:
                        pip_size = spec.get('pipSize', tick_size)  # Unknown - use broker value
                    
                    # Calculate pip value from tick value
                    # profitTickValue is per tick, so scale to our pip size
                    ticks_per_pip = pip_size / tick_size if tick_size > 0 else 1
                    pip_value = profit_tick_value * ticks_per_pip
                    
                    logger.info(f"📊 {symbol} PIP VALUE (from profitTickValue):")
                    logger.info(f"   profitTickValue: ${profit_tick_value:.4f}")
                    logger.info(f"   tick_size: {tick_size}")
                    logger.info(f"   pip_size: {pip_size}")
                    logger.info(f"   ticks_per_pip: {ticks_per_pip}")
                    logger.info(f"   FINAL pip_value: ${pip_value:.4f}/lot")
                    return pip_value
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
            
            # Fallback: Calculate from specification
            spec = await self.trading_provider.get_symbol_specification(symbol)
            
            tick_size = spec.get('tickSize', 0.00001)
            contract_size = spec.get('contractSize', 100000)
            digits = spec.get('digits', 5)
            
            # Determine correct pip size - CHECK INSTRUMENT TYPE FIRST before digits
            # This prevents XAUUSD (digits=5) from being caught by standard forex condition,
            # and ensures JPY pairs are detected by name even when broker reports digits=5.

            # Gold/XAU - check first!
            if 'XAU' in symbol.upper() or 'GOLD' in symbol.upper():
                pip_size = 0.1
                logger.debug(f"📊 {symbol}: Gold, pip_size=0.1")

            # Crypto - check second
            elif 'BTC' in symbol.upper() or 'ETH' in symbol.upper():
                pip_size = 1.0 if digits <= 2 else 0.1
                logger.debug(f"📊 {symbol}: Crypto, pip_size={pip_size}")

            # JPY pairs by name - check before digits (some brokers report digits=5 for JPY)
            elif 'JPY' in symbol.upper() or 'HUF' in symbol.upper() or 'CZK' in symbol.upper():
                pip_size = 0.01
                logger.debug(f"📊 {symbol}: JPY-quote pair (by name), pip_size=0.01")

            # JPY-like by digits (fallback for unlisted currencies)
            elif digits == 3 or digits == 2:
                pip_size = 0.01
                logger.debug(f"📊 {symbol}: JPY-like pair (digits={digits}), pip_size=0.01")

            # Standard forex pairs
            elif digits == 5 or digits == 4:
                pip_size = 0.0001  # Standard forex pairs
                logger.debug(f"📊 {symbol}: Standard forex (digits={digits}), pip_size=0.0001")

            else:
                # Unknown instrument - use broker value but warn
                pip_size = spec.get('pipSize', tick_size)
                logger.warning(f"⚠️ {symbol}: Unknown instrument, using broker pip_size={pip_size}")
            
            # Base calculation: pip_value = pip_size × contract_size
            # For JPY pairs the profit is in JPY, so divide by the exchange rate to get USD.
            # (pip_size × contract_size gives ~$1,000 for USDJPY which is 100× too high.)
            pip_value = pip_size * contract_size
            if 'JPY' in symbol.upper() or 'HUF' in symbol.upper() or 'CZK' in symbol.upper():
                try:
                    price_data = await self.trading_provider.get_symbol_price(symbol)
                    mid = (price_data.get('ask', 0) + price_data.get('bid', 0)) / 2
                    if mid > 0:
                        pip_value = pip_value / mid
                        logger.debug(f"📊 {symbol}: JPY-quote pair, divided pip_value by rate {mid:.3f}")
                except Exception:
                    self._pip_estimated[symbol] = True
                    pip_value = 10.0  # safe fallback (~correct for most JPY pairs)
                    logger.warning(f"⚠️ {symbol}: Could not fetch price for JPY pip conversion, using $10 fallback")

            # Log for debugging
            logger.info(f"📊 {symbol} PIP VALUE (from specification):")
            logger.info(f"   contract_size: {contract_size}")
            logger.info(f"   pip_size: {pip_size}")
            logger.info(f"   digits: {digits}")
            logger.info(f"   FINAL pip_value: ${pip_value:.4f}/lot")
            if contract_size < 1000:
                logger.info("   Type: Crypto/CFD")
            else:
                logger.info("   Type: Forex/Metals")
            
            return pip_value
            
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch pip value for {symbol}, using default: {str(e)}")
            self._pip_estimated[symbol] = True
            # Fallback to simplified logic
            if "JPY" in symbol:
                return 10.0
            elif "XAU" in symbol or "GOLD" in symbol:
                return 10.0
            elif "XAG" in symbol or "SILVER" in symbol:
                return 50.0
            elif "BTC" in symbol or "ETH" in symbol:
                return 1.0  # $1 per pip per lot for crypto
            else:
                return 10.0
    
    async def _get_pip_multiplier(self, symbol: str) -> float:
        """
        Get pip multiplier for calculating pips from price difference
        
        IMPORTANT: Pips vs Points for Standard Accounts
        - For most forex pairs: 1 pip = 0.0001 (4th decimal)
        - Points (pipettes): 1 point = 0.00001 (5th decimal)
        - For JPY pairs: 1 pip = 0.01 (2nd decimal)
        - Brokers often return tickSize (points) as pipSize, causing wrong calculations
        """
        try:
            # Fetch symbol specification from broker
            spec = await self.trading_provider.get_symbol_specification(symbol)
            
            tick_size = spec.get('tickSize', 0.00001)
            digits = spec.get('digits', 5)
            broker_pip_size = spec.get('pipSize', tick_size)
            
            # Determine proper pip size - CHECK INSTRUMENT TYPE FIRST before digits
            # This prevents XAUUSD (digits=5) from being caught by standard forex condition,
            # and ensures JPY pairs are detected by name even when broker reports digits=5.

            # Gold/XAU - check first!
            if 'XAU' in symbol.upper() or 'GOLD' in symbol.upper():
                pip_size = 0.1  # For gold, 1 pip = 0.1
                logger.debug(f"📊 {symbol}: Gold instrument (digits={digits}), using pip_size=0.1")

            # Crypto - check second
            elif 'BTC' in symbol.upper() or 'ETH' in symbol.upper():
                if digits <= 2:
                    pip_size = 1.0
                else:
                    pip_size = 0.1
                logger.debug(f"📊 {symbol}: Crypto instrument (digits={digits}), using pip_size={pip_size}")

            # JPY pairs by name - check before digits (some brokers report digits=5 for JPY)
            elif 'JPY' in symbol.upper() or 'HUF' in symbol.upper() or 'CZK' in symbol.upper():
                pip_size = 0.01
                logger.debug(f"📊 {symbol}: JPY-quote pair (by name), using pip_size=0.01")

            # JPY-like by digits (fallback for unlisted currencies)
            elif digits == 3 or digits == 2:
                pip_size = 0.01
                logger.debug(f"📊 {symbol}: JPY-like pair (digits={digits}), using pip_size=0.01")

            # Standard forex pairs (EURUSD, GBPUSD, etc.)
            elif digits == 5 or digits == 4:
                pip_size = 0.0001
                logger.debug(f"📊 {symbol}: Standard forex pair (digits={digits}), using pip_size=0.0001")

            # Unknown instrument - use broker value but warn
            else:
                pip_size = broker_pip_size
                logger.warning(f"⚠️ {symbol}: Unknown instrument type (digits={digits}), using broker pip_size={pip_size}")
            
            # Calculate multiplier: multiplier converts price difference to pip count
            # If price moves 0.0010 and pip_size is 0.0001, that's 10 pips
            multiplier = 1 / pip_size
            
            logger.debug(f"📊 {symbol}: digits={digits}, tick={tick_size}, pip_size={pip_size}, multiplier={multiplier}, broker_pip_size={broker_pip_size}")
            
            return multiplier
            
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch pip multiplier for {symbol}, using default: {str(e)}")
            # Fallback to simplified logic
            if "JPY" in symbol:
                return 100  # 1/0.01 = 100
            elif "XAU" in symbol or "GOLD" in symbol:
                return 10  # 1/0.1 = 10
            elif "BTC" in symbol or "ETH" in symbol:
                return 1  # 1/1.0 = 1
            else:
                return 10000  # 1/0.0001 = 10000 (standard forex)
    
    async def _fetch_current_price(self, symbol: str, signal_type: SignalType) -> float:
        """Fetch current market price for a symbol"""
        try:
            price_data = await self.trading_provider.get_symbol_price(symbol)
            
            # Use ask for buy, bid for sell
            if signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]:
                return price_data['ask']
            else:
                return price_data['bid']
        except Exception as e:
            error_msg = str(e)
            if "No price data available" in error_msg or "market may be closed" in error_msg:
                logger.error(f"Failed to fetch price for {symbol}: {e}")
                raise Exception(f"No price data available for {symbol} - market may be closed") from e
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            raise
    
    async def _adjust_stop_loss_for_spread(
        self,
        signal: TradingSignal,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """
        Adjust stop loss to account for spread to prevent immediate closure
        
        For BUY orders: Move SL further DOWN (subtract spread * multiplier)
        For SELL orders: Move SL further UP (add spread * multiplier)
        """
        from src.models import OrderType
        
        # Get current spread
        try:
            price_data = await self.trading_provider.get_symbol_price(signal.symbol)
            spread = price_data['ask'] - price_data['bid']
            adjustment = spread * settings.spread_adjustment_multiplier
            logger.info(f"📊 Spread: {spread:.5f}, Adjustment: {adjustment:.5f} (multiplier: {settings.spread_adjustment_multiplier})")
        except Exception as e:
            error_msg = str(e)
            if "No price data available" in error_msg or "market may be closed" in error_msg:
                logger.warning(f"⚠️ Could not adjust SL for spread (no price data): {e}")
                return stop_loss  # Return original if we can't get spread
            logger.warning(f"⚠️ Could not adjust SL for spread: {e}")
            return stop_loss  # Return original if we can't adjust
        
        # Determine if this is a BUY order
        is_buy = False
        if signal.order_type:
            is_buy = (signal.order_type == OrderType.BUY)
        elif signal.signal_type:
            is_buy = signal.signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]
        else:
            is_buy = True  # Default to BUY
        
        # Adjust based on order direction
        if is_buy:
            # For BUY: SL is below entry, move it further down
            adjusted_sl = stop_loss - adjustment
        else:
            # For SELL: SL is above entry, move it further up
            adjusted_sl = stop_loss + adjustment
        
        return round(adjusted_sl, 5)
    
    def _is_buy_signal(self, signal: TradingSignal) -> bool:
        """Resolve trade direction from order_type, falling back to signal_type."""
        from src.models import OrderType
        if signal.order_type:
            return signal.order_type == OrderType.BUY
        if signal.signal_type:
            return signal.signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]
        return True  # Default to BUY to avoid dangerous placement

    async def _get_spread_adjustment(self, signal: TradingSignal) -> float:
        """
        Return the raw spread adjustment amount (spread × multiplier) for a symbol,
        or 0.0 if disabled or the spread can't be fetched. Direction-agnostic —
        callers add it for BUY and subtract it for SELL.
        """
        if settings.spread_adjustment_multiplier == 0:
            return 0.0
        try:
            price_data = await self.trading_provider.get_symbol_price(signal.symbol)
            spread = price_data['ask'] - price_data['bid']
            adjustment = spread * settings.spread_adjustment_multiplier
            logger.info(f"📊 Entry spread: {spread:.5f}, Adjustment: {adjustment:.5f} (multiplier: {settings.spread_adjustment_multiplier})")
            return adjustment
        except Exception as e:
            error_msg = str(e)
            if "No price data available" in error_msg or "market may be closed" in error_msg:
                logger.warning(f"⚠️ Could not adjust entry for spread (no price data): {e}")
            else:
                logger.warning(f"⚠️ Could not adjust entry for spread: {e}")
            return 0.0  # Leave entry untouched if we can't get spread

    async def _adjust_entry_for_spread(
        self,
        signal: TradingSignal,
        entry_price: float
    ) -> float:
        """
        Adjust a single entry level for spread — the opposite of the SL adjustment.

        For BUY orders:  Move entry further UP   (add spread * multiplier)
        For SELL orders: Move entry further DOWN (subtract spread * multiplier)

        Example: BUY entry 2300, spread 0.2, multiplier 2 → 2300 + 0.4 = 2300.40
                 SELL entry 2300, spread 0.2, multiplier 2 → 2300 - 0.4 = 2299.60
        """
        adjustment = await self._get_spread_adjustment(signal)
        if not adjustment:
            return entry_price
        delta = adjustment if self._is_buy_signal(signal) else -adjustment
        return round(entry_price + delta, 5)

    async def _calculate_default_stop_loss(
        self,
        signal: TradingSignal,
        entry_price: float,
        symbol: str
    ) -> float:
        """Calculate default stop loss based on configured pips (60 pips)"""
        from src.models import OrderType
        
        pip_multiplier = await self._get_pip_multiplier(symbol)
        pip_size = 1 / pip_multiplier
        pips = settings.default_stop_loss_pips  # Now 60 pips
        
        # Determine if this is a BUY order - check order_type first, then signal_type
        is_buy = False
        if signal.order_type:
            is_buy = (signal.order_type == OrderType.BUY)
            logger.debug(f"📊 SL direction from order_type: {'BUY' if is_buy else 'SELL'}")
        elif signal.signal_type:
            is_buy = signal.signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]
            logger.debug(f"📊 SL direction from signal_type: {'BUY' if is_buy else 'SELL'}")
        else:
            logger.error("🚨 Cannot determine order direction - no signal_type or order_type!")
            # Default to BUY to avoid dangerous SL placement
            is_buy = True
        
        if is_buy:
            # BUY: SL should be BELOW entry (subtract pips)
            sl = entry_price - (pips * pip_size)
            logger.debug(f"📊 BUY SL calculation: {entry_price} - ({pips} * {pip_size}) = {sl}")
            return sl
        else:
            # SELL: SL should be ABOVE entry (add pips)
            sl = entry_price + (pips * pip_size)
            logger.debug(f"📊 SELL SL calculation: {entry_price} + ({pips} * {pip_size}) = {sl}")
            return sl
    
    async def _calculate_default_take_profit(
        self,
        signal: TradingSignal,
        entry_price: float,
        symbol: str
    ) -> float:
        """Calculate default take profit based on risk-reward ratio"""
        from src.models import OrderType
        
        pip_multiplier = await self._get_pip_multiplier(symbol)
        pip_size = 1 / pip_multiplier
        pips = settings.default_take_profit_pips
        
        # Determine if this is a BUY order - check order_type first, then signal_type
        is_buy = False
        if signal.order_type:
            is_buy = (signal.order_type == OrderType.BUY)
        elif signal.signal_type:
            is_buy = signal.signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]
        else:
            # Default to BUY
            is_buy = True
        
        if is_buy:
            # BUY: TP should be ABOVE entry (add pips)
            return entry_price + (pips * pip_size)
        else:
            # SELL: TP should be BELOW entry (subtract pips)
            return entry_price - (pips * pip_size)
    

risk_manager = RiskManager()
