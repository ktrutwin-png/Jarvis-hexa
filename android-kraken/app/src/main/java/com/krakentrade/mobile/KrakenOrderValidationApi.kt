package com.krakentrade.mobile

class KrakenOrderValidationApi(
    private val transport: KrakenPrivateTransport
) {
    suspend fun validateEntry(proposal: ExecutableProposal): Result<String> {
        val validation = ProposalValidator.validate(proposal, RiskPolicy())
        if (validation is ValidationResult.Invalid) {
            return Result.failure(IllegalArgumentException(validation.reason))
        }
        return transport.post(
            "/0/private/AddOrder",
            linkedMapOf(
                "ordertype" to "limit",
                "type" to proposal.side.name.lowercase(),
                "volume" to decimal(proposal.volume),
                "pair" to proposal.pair.replace("/", ""),
                "price" to decimal(proposal.entry),
                "cl_ord_id" to proposal.id.take(18),
                "validate" to "true"
            )
        ).fold(
            onSuccess = { KrakenResponse.requireSuccess(it) },
            onFailure = { Result.failure(it) }
        )
    }

    private fun decimal(value: Double): String =
        java.math.BigDecimal.valueOf(value).stripTrailingZeros().toPlainString()
}
