package com.krakentrade.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

data class TradeProposal(
    val pair: String, val side: String, val entry: String,
    val stopLoss: String, val takeProfit: String, val maxRisk: String
)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { ProposalScreen(
            TradeProposal("XRP/EUR", "WAIT", "—", "—", "—", "—")
        ) } }
    }
}

@Composable
fun ProposalScreen(p: TradeProposal) {
    Scaffold { padding ->
        Column(Modifier.padding(padding).padding(24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Kraken Trade", style = MaterialTheme.typography.headlineMedium)
            Text("Propozycja transakcji", style = MaterialTheme.typography.titleLarge)
            Text("Para: ${p.pair}")
            Text("Kierunek: ${p.side}")
            Text("Wejście: ${p.entry}")
            Text("Stop-loss: ${p.stopLoss}")
            Text("Take-profit: ${p.takeProfit}")
            Text("Maks. ryzyko: ${p.maxRisk}")
            Button(onClick = { /* approval will call guarded execution layer */ }, enabled = p.side != "WAIT", modifier = Modifier.fillMaxWidth()) { Text("ZATWIERDŹ") }
            OutlinedButton(onClick = { }, modifier = Modifier.fillMaxWidth()) { Text("ODRZUĆ") }
            Text("Zlecenie nie zostanie wysłane bez ręcznego zatwierdzenia.")
        }
    }
}
