package com.krakentrade.mobile

import android.content.Context
import java.util.UUID

data class KrakenReadiness(
    val credentialsPresent: Boolean,
    val canQueryFunds: Boolean,
    val canQueryOrders: Boolean,
    val canModifyTrades: Boolean,
    val canCloseTrades: Boolean
) {
    val readyForAnalysis: Boolean
        get() = credentialsPresent && canQueryFunds

    val readyForOrderValidation: Boolean
        get() = credentialsPresent && canModifyTrades
}

class KrakenAppRuntime(context: Context) {
    private val credentialStore = AndroidKeystoreCredentialStore(context)

    fun hasCredentials(): Boolean = credentialStore.load() != null

    fun saveCredentials(credentials: KrakenCredentials) {
        credentialStore.save(credentials)
    }

    fun clearCredentials() {
        credentialStore.clear()
    }

    suspend fun readiness(): Result<KrakenReadiness> {
        val credentials = credentialStore.load()
            ?: return Result.success(
                KrakenReadiness(
                    credentialsPresent = false,
                    canQueryFunds = false,
                    canQueryOrders = false,
                    canModifyTrades = false,
                    canCloseTrades = false
                )
            )

        val account = KrakenAccountApi(transport(credentials))
        return account.getApiKeyStatus().map { status ->
            KrakenReadiness(
                credentialsPresent = true,
                canQueryFunds = "query-funds" in status.permissions,
                canQueryOrders = "query-open-trades" in status.permissions ||
                    "query-closed-trades" in status.permissions,
                canModifyTrades = "modify-trades" in status.permissions,
                canCloseTrades = "close-trades" in status.permissions
            )
        }
    }

    suspend fun analyzePair(
        pair: String,
        intervalMinutes: Int = 5,
        strategy: StrategyConfig = StrategyConfig()
    ): Result<ProposalDecision> {
        val credentials = credentialStore.load()
            ?: return Result.failure(IllegalStateException("Brak zapisanych danych API"))

        val privateTransport = transport(credentials)
        val service = TradingAnalysisService(
            market = KrakenPublicMarketApi(),
            pairs = KrakenAssetPairsApi(),
            balances = KrakenBalanceApi(privateTransport)
        )
        return service.analyze(
            pair = pair,
            intervalMinutes = intervalMinutes,
            strategy = strategy,
            proposalId = UUID.randomUUID().toString()
        )
    }

    suspend fun validateApprovedProposal(
        proposal: ExecutableProposal
    ): Result<String> {
        val credentials = credentialStore.load()
            ?: return Result.failure(IllegalStateException("Brak zapisanych danych API"))

        val privateTransport = transport(credentials)
        val gate = ApprovalGate()
        val coordinator = BracketExecutionCoordinator(KrakenOrderApi(privateTransport))
        val executor = TradeExecutor(
            api = KrakenTradeExecutionApi(coordinator, ExecutionMode.VALIDATE_ONLY),
            gate = gate
        )
        val session = TradeSession(executor, gate)
        session.present(proposal)
        return session.approveAndExecute()
    }

    private fun transport(credentials: KrakenCredentials): KrakenPrivateTransport =
        KrakenPrivateTransport(credentialsProvider = { credentials })
}
