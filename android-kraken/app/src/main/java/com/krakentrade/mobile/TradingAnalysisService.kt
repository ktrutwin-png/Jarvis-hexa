package com.krakentrade.mobile

class TradingAnalysisService(
    private val market: MarketDataGateway,
    private val pairs: PairRulesGateway,
    private val balances: BalanceGateway
) {
    suspend fun analyze(
        pair: String,
        intervalMinutes: Int = 5,
        strategy: StrategyConfig = StrategyConfig(),
        proposalId: String
    ): Result<ProposalDecision> = runCatching {
        val rules = pairs.fetchPair(pair).getOrThrow()
        require(rules.isOnline) { "Para nie jest dostępna do handlu" }

        val candles = market.fetchOhlc(pair, intervalMinutes).getOrThrow()
        val indicators = MarketIndicatorCalculator.calculate(candles)
        val balanceMap = balances.fetchBalances().getOrThrow()

        val baseBalance = balanceMap[rules.baseAsset] ?: 0.0
        val quoteBalance = balanceMap[rules.quoteAsset] ?: 0.0
        val capacity = AccountCapacity(
            quoteBalance = quoteBalance,
            baseBalance = baseBalance,
            accountEquityQuote = quoteBalance + baseBalance * indicators.lastClose
        )

        when (val decision = ProposalEngine.build(
            pair = rules.displayName,
            indicators = indicators,
            capacity = capacity,
            config = strategy,
            proposalId = proposalId
        )) {
            is ProposalDecision.Wait -> decision
            is ProposalDecision.Trade -> {
                val normalized = PairOrderRules.normalize(decision.proposal, rules).getOrThrow()
                ProposalDecision.Trade(normalized.proposal.copy(pair = rules.displayName))
            }
        }
    }
}
