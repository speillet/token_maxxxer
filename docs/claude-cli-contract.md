# Contrat Claude Code — validation documentaire

Vérification documentaire : 2 novembre 2026. **Contrat provisoire, jalon 0 non
validé en conditions réelles.** Le binaire `claude` n'est pas présent dans le PATH
de développement. Aucune version compatible ni fixture observée n'est annoncée.

## Accès et facturation

La [mise à jour officielle sur l'Agent SDK et les abonnements](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
indique que `claude -p`, connecté au compte Claude, utilise encore les limites de
l'abonnement. Cette règle externe doit être revalidée au premier pilote.
L'application n'extrait aucun jeton et ne fait aucun appel HTTP avec OAuth.

Une [clé API d'environnement prend priorité sur la connexion abonnement](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code).
Le diagnostic doit signaler les noms des variables incompatibles sans afficher
leurs valeurs. Les fournisseurs tiers et les helpers de clé nécessitent aussi
un contrôle. Le socle ne garantit pas l'absence de configuration héritée des
settings ou de politique administrée : l'audit complet précède l'exécuteur.

Les [limites sont partagées avec Claude et des crédits supplémentaires sont possibles](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-max-or-ultra-plan).
L'utilisateur doit vérifier dans son compte que ces crédits sont désactivés.
Un diagnostic local ne peut pas attester ce réglage. Quota restant :
**indisponible dans le contrat retenu** ; aucune interface officielle stable
lisible par l'application n'a été validée. Une donnée absente reste inconnue.

## Commandes à qualifier au jalon 2

La [référence du CLI](https://code.claude.com/docs/en/cli-reference) décrit :

- `claude --version` pour enregistrer la version installée ;
- `claude auth status` pour le diagnostic JSON sans inférence ; accepter
  `loggedIn: true` et `authMethod: claude.ai` pour le parcours retenu ;
- `-p`, `--output-format json`, `--max-turns` et `--resume <session>` ;
- `--tools` pour restreindre les outils disponibles et `--allowedTools` pour
  définir les permissions ; pas de désactivation globale des permissions.

La [documentation programmatique](https://code.claude.com/docs/en/headless)
précise qu'une erreur peut apparaître dans le résultat stdout. Vérifier ensemble
le code de sortie et le contenu structuré ; un code zéro seul ne suffit pas.
Le mode `--bare` n'utilise pas la connexion abonnement : ne pas l'employer dans
ce parcours. Sans ce mode, les hooks et MCP peuvent se charger en non interactif ;
ils doivent être audités avant un premier lancement.

## Classification prévue

| Résultat normalisé | Signal requis |
| --- | --- |
| `success` | Sortie structurée valide, fin réussie et absence d'erreur interne ; ne vaut pas validation des tests |
| `rate_limited` | Signal de limite confirmé pour la version qualifiée ; reprise connue ou backoff borné |
| `auth_error` | Authentification absente, expirée ou incompatible ; intervention plutôt que boucle quota |
| `timeout` | Délai local expiré ; arrêt du groupe de processus |
| `transient_error` | Erreur temporaire identifiée ; nombre de reprises borné |
| `invalid_output` | Format inconnu, tronqué ou incohérent ; conserver un diagnostic expurgé |

Les codes et formes exactes des erreurs ne sont pas encore qualifiés. Ne pas
inventer de code quota ou traiter toute erreur comme un incident transitoire.

## Contrat implémenté hors ligne au jalon 2

L'adaptateur lit un unique objet terminal JSON, avec `type: result`, `subtype`
et un booléen strict `is_error`. Les clés dupliquées, formats inconnus et sorties
tronquées et champs inconnus sont refusés. Les métadonnées reconnues incluent les
durées, tours, UUID, cache, `modelUsage`, `permission_denials` et `structured_output`.
La [référence officielle ResultMessage](https://code.claude.com/docs/en/agent-sdk/python#resultmessage)
décrit notamment `api_error_status`, `terminal_reason` et les champs d'usage.
Même un sous-type `success` peut porter une erreur : le parseur contrôle ce cas.
Le SDK n'est pas une dépendance du projet ; seul le CLI est exécuté.

Politique locale pour un message avec `is_error: true` :

| Statut HTTP structuré | Classification |
| --- | --- |
| 401 ou 403 | `auth_error` ; intervention nécessaire, aucune relance |
| 429 | `rate_limited` ; réinitialisation inconnue dans ce format |
| 408 ou 5xx | `transient_error` ; aucune relance dans le transport |
| Autre ou absent | `invalid_output` ; revue, sans déduire un quota depuis du texte |

Un message sans erreur doit aussi annoncer `subtype: success`, contenir un
résultat texte, une fin `completed` (ou absente) et une raison d'arrêt
`end_turn`, `stop_sequence` (ou absente), sans erreurs contradictoires, puis finir avec le code
zéro. Un crash sans résultat exploitable est `invalid_output`. Un dépassement de
délai est `timeout`. Les tokens et coût restent `None` lorsqu'ils sont absents ;
un coût fourni est une estimation et ne prouve pas la facturation réelle.

L'adaptateur exige une qualification explicite de la version exacte et du
workspace, incluant les vérifications humaines du compte et des settings. Cette
attestation n'est pas une preuve automatique ni une isolation de sécurité.
Il vérifie `--version` et `auth status` avant chaque tentative, refuse les
variables d'environnement incompatibles et ne restitue pas les données de compte.
`--tools` et `--allowedTools` limitent les outils autorisés ; `dontAsk` et
`--permission-prompts none` refusent les permissions imprévues. Ce dernier flag
nécessite au moins la version documentaire 2.1.259, sans que ce minimum soit une
version réellement qualifiée. Les MCP sont désactivés par configuration vide
stricte ; les settings utilisateur/projet ne sont pas chargés. Les politiques
administrées restent à auditer.

La consigne passe par stdin. Les flux stdout/stderr sont séparés et leurs valeurs
retournées sont plafonnées à 1 Mio par flux. La taille temporaire est surveillée
par sondages pendant le processus ; ce plafond n'est pas une limite disque dure.
Les formats de clés reconnus, Bearer et champs de credentials usuels sont masqués
avant restitution, y compris le JSON décodé et les valeurs citées avec espaces.
En texte invalide ou tronqué, la fin d'une ligne portant un champ de credential
est supprimée. Ce filtre ne remplace pas l'audit des données à journaliser.
Le timeout, l'interruption clavier et la sortie normale nettoient le groupe de
processus (SIGTERM puis SIGKILL après grâce). Un descendant qui crée sa propre
session sort de cette garantie de groupe ; aucune sandbox système n'est annoncée.
Un arrêt brutal de l'appelant ne déroule pas ces garanties : les gestionnaires
SIGTERM du superviseur seront raccordés avec l'exécution et le service ; SIGKILL
ne permet pas un nettoyage Python. Ce lot n'installe aucun service.

Les [fixtures synthétiques](../tests/fixtures/claude/README.md) et le faux CLI
n'appellent aucun service externe. La version `2.1.999` est fictive. Le pilote
doit encore confirmer les options, les métadonnées et les vrais signaux d'erreur.

## Validation restante

1. Installer le CLI officiel et enregistrer sa version et son aide.
2. Suivre `claude auth login`, puis contrôler la méthode de connexion, les
   settings effectifs, fournisseurs et variables d'environnement.
3. Vérifier les crédits supplémentaires et les conditions en vigueur du compte.
4. Dans un dépôt de démonstration audité, envoyer une consigne minimale via stdin
   avec `-p --output-format json --max-turns 1 --tools ""` ; vérifier les options
   sur cette version avant de lancer la commande.
5. Examiner résultat, usage éventuellement fourni et mode de facturation.
   Conserver une fixture anonymisée avec provenance et version. Simuler les
   erreurs ensuite ; ne pas épuiser volontairement l'allocation.

Le développement du socle et les tests locaux restent possibles sans connexion.
Les commandes réelles `run --once` et service restent indisponibles dans ce lot.
