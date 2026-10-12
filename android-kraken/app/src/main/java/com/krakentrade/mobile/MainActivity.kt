package com.krakentrade.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                KrakenTradeApp()
            }
        }
    }
}

@Composable
fun KrakenTradeApp() {
    val context = LocalContext.current
    val runtime = remember { KrakenAppRuntime(context) }
    var hasCredentials by remember { mutableStateOf(runtime.hasCredentials()) }

    if (!hasCredentials) {
        CredentialScreen(
            onSave = { apiKey, apiSecret ->
                runtime.saveCredentials(KrakenCredentials(apiKey, apiSecret))
                hasCredentials = true
            }
        )
    } else {
        TradingScreen(
            runtime = runtime,
            onClearCredentials = {
                runtime.clearCredentials()
                hasCredentials = false
            }
        )
    }
}

@Composable
private fun CredentialScreen(
    onSave: (String, String) -> Unit
) {
    var apiKey by remember { mutableStateOf("") }
    var apiSecret by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    Scaffold { padding ->
        Column(
            modifier = Modifier.padding(padding).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Text("NexTrade", style = MaterialTheme.typography.headlineMedium)
            Text("Połączenie API", style = MaterialTheme.typography.titleLarge)
            Text("Klucze są szyfrowane kluczem z Android Keystore i nie są zapisywane w repozytorium.")

            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it.trim() },
                label = { Text("API Key") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )
            OutlinedTextField(
                value = apiSecret,
                onValueChange = { apiSecret = it.trim() },
                label = { Text("API Secret") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password)
            )

            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

            Button(
                onClick = {
                    if (apiKey.isBlank() || apiSecret.isBlank()) {
                        error = "Wpisz oba pola API."
                    } else {
                        error = null
                        onSave(apiKey, apiSecret)
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("ZAPISZ BEZPIECZNIE")
            }
        }
    }
}

@Composable
private fun TradingScreen(
    runtime: KrakenAppRuntime,
    onClearCredentials: () -> Unit
) {
    val scope = rememberCoroutineScope()
    var pair by remember { mutableStateOf("XRP/EUR") }
    var proposal by remember { mutableStateOf<ExecutableProposal?>(null) }
    var status by remember { mutableStateOf("Gotowy do analizy.") }
    var busy by remember { mutableStateOf(false) }

    Scaffold { padding ->
        Column(
            modifier = Modifier.padding(padding).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text("NexTrade", style = MaterialTheme.typography.headlineMedium)
            Text("Tryb: WALIDACJA — bez realnych zleceń")
            Text("Realne wykonanie pozostaje zablokowane, dopóki pełna ochrona SL/TP i monitoring nie przejdą testów.")

            OutlinedTextField(
                value = pair,
                onValueChange = { pair = it.uppercase() },
                label = { Text("Para") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )

            Button(
                onClick = {
                    busy = true
                    status = "Analizuję dane Kraken..."
                    scope.launch {
                        runtime.analyzePair(pair).fold(
                            onSuccess = { decision ->
                                when (decision) {
                                    is ProposalDecision.Wait -> {
                                        proposal = null
                                        status = "WAIT: " + decision.reason
                                    }
                                    is ProposalDecision.Trade -> {
                                        proposal = decision.proposal
                                        status = "Propozycja gotowa do ręcznego zatwierdzenia."
                                    }
                                }
                            },
                            onFailure = {
                                proposal = null
                                status = it.message ?: "Błąd analizy"
                            }
                        )
                        busy = false
                    }
                },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (busy) "ANALIZA..." else "ANALIZUJ")
            }

            proposal?.let { p ->
                ProposalCard(p)

                Button(
                    onClick = {
                        busy = true
                        status = "Waliduję zlecenie po zatwierdzeniu..."
                        scope.launch {
                            runtime.validateApprovedProposal(p).fold(
                                onSuccess = {
                                    status = "Kraken zaakceptował parametry w trybie walidacji. Realne zlecenie nie zostało wysłane."
                                },
                                onFailure = {
                                    status = it.message ?: "Walidacja zlecenia nie powiodła się"
                                }
                            )
                            busy = false
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("ZATWIERDŹ I SPRAWDŹ W KRAKEN")
                }

                OutlinedButton(
                    onClick = {
                        proposal = null
                        status = "Propozycja odrzucona."
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("ODRZUĆ")
                }
            }

            Card(modifier = Modifier.fillMaxWidth()) {
                Text(status, modifier = Modifier.padding(16.dp))
            }

            OutlinedButton(
                onClick = onClearCredentials,
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("USUŃ DANE API Z TELEFONU")
            }
        }
    }
}

@Composable
private fun ProposalCard(p: ExecutableProposal) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Text("Propozycja transakcji", style = MaterialTheme.typography.titleLarge)
            Row(Modifier.fillMaxWidth()) {
                Text("Para: " + p.pair, modifier = Modifier.weight(1f))
                Text("Kierunek: " + p.side.name)
            }
            Text("Wejście: " + p.entry)
            Text("Stop-loss: " + p.stopLoss)
            Text("Take-profit: " + p.takeProfit)
            Text("Wolumen: " + p.volume)
            Text("Maks. ryzyko: " + p.maxRiskPct + "%")
        }
    }
}
