# Contrat fournisseurs — token_maxxxer

Le port `Provider.generate(GenerationRequest, SecretStr)` retourne un
`RunnerResult`. Les paramètres incluent le fournisseur, le modèle explicite,
le plafond de sortie et le timeout HTTP. `query` génère du texte ; les outils de
modification de code et la vérification de tâches seront raccordés au jalon 3.

## Implémentations

| Fournisseur | Transport | Credential | État |
| --- | --- | --- | --- |
| Claude | SDK Anthropic, Messages API | `ANTHROPIC_API_KEY` ou référence privée | Implémenté, testé sur HTTP simulé |
| OpenAI | SDK OpenAI, Responses API | `OPENAI_API_KEY` ou référence privée | Implémenté, testé sur HTTP simulé |
| GitHub Copilot | SDK Copilot officiel | Token GitHub autorisé | À implémenter ; sélection refusée clairement |

Les endpoints API sont explicites. Les variables de base URL ne redirigent pas
les clés vers un autre hôte, les redirections HTTP sont désactivées et le client
HTTP n'hérite pas de proxy d'environnement. Les SDK n'effectuent aucune reprise
automatique. Aucun second fournisseur n'est appelé si le premier échoue.

## Résultats et limites

- `success` signifie une réponse complète et textuelle, sans erreur interne.
  Cela ne change pas l'état d'une tâche et ne prouve pas ses critères métier.
- 401/403 deviennent `auth_error`, 429 devient `rate_limited`, 408/5xx et les
  erreurs de connexion deviennent `transient_error`. Le timeout devient `timeout`.
- Une réponse malformée, un refus ou une génération incomplète est
  `invalid_output`. Les messages d'exception, en-têtes et corps d'erreur ne sont
  jamais restitués dans les diagnostics.
- Tokens et coût absents restent inconnus. Aucun quota restant ni coût exact
  n'est déduit du nombre de tokens. Le timeout HTTP ne constitue pas encore un
  watchdog global de fenêtre ou un budget financier garanti.

Les tests interceptent le transport HTTP des SDK avec des clés fictives. La
qualification réelle d'un compte reste ouverte ; aucun test ne facture une API.

## Credentials

La clé du fournisseur choisi est cherchée dans sa variable d'environnement,
puis sa référence `TOKEN_MAXXXER_<FOURNISSEUR>_CREDENTIAL_REF` dans l'environnement
ou le `.env` privé. Le lecteur ne modifie pas `os.environ` et ne fait aucune
interpolation. Il refuse les valeurs de clés API en clair dans `.env`.

Les références `keychain://service/compte` sont résolues sur macOS à la demande
de `query`, par l'outil système, avec timeout et sans sortie du secret. `doctor`
vérifie seulement la configuration et ne déchiffre rien. Sur Linux, les variables
de processus sont actuellement le mode pris en charge. Les références ne sont
pas des secrets et ne créent aucune entrée de Trousseau automatiquement.

## Sources officielles vérifiées le 2 novembre 2026

- [Claude Messages](https://platform.claude.com/docs/en/api/messages) : modèle,
  messages utilisateur, plafond de sortie, contenu et usage de la réponse.
- [Modèles Claude](https://platform.claude.com/docs/en/models/overview) : identifiants
  des modèles d'exemple ; l'accès du compte n'est pas vérifié par la documentation.
- [OpenAI Responses](https://developers.openai.com/api/reference/python/resources/responses/methods/create) :
  `input`, `max_output_tokens`, statut de génération et sortie texte. L'adaptateur
  demande `store=False`.
- [Authentification Copilot SDK](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/authenticate) :
  authentification et tokens GitHub propres à Copilot. Ce contrat prévoit un
  adaptateur SDK dédié, sans URL privée ni réutilisation implicite de `gh auth`.

Le prototype abonnement/CLI est conservé dans
[l'archive du contrat CLI](archive/claude-cli-contract.md). Il n'est pas requis
pour les appels API Claude ou OpenAI.
