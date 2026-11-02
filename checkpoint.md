# Checkpoints — token_maxxxer

Mis à jour le 2 novembre 2026. Ce fichier suit les livraisons du code ; il ne
remplace pas les checkpoints d'exécution LangGraph du futur jalon 4.

## Cadrage actualisé

Le nom du dépôt, du paquet et de la commande est `token_maxxxer`. La demande
actuelle remplace le cadrage initial centré sur un abonnement : Claude via clé
API devient le premier backend, OpenAI rejoint l'interface commune et Copilot
sera raccordé via son SDK/authentification GitHub officielle. Les preuves et
commits précédents restent des points de retour historiques.

## État du projet

| Jalon | État | Preuves / suite |
| --- | --- | --- |
| 0 — Abonnement | Partiel | Contrat documentaire ; CLI absent de cette machine, validation du compte et appel réel à faire |
| 1 — Socle Python | Socle livré | Configuration, modèles, SQLite, CLI en lecture/simulation et tests locaux ; modules d'exécution aux jalons suivants |
| 2 — Exécuteur | Livré hors ligne, pilote ouvert | Résultat normalisé, faux exécuteur et transport subprocess ; qualification réelle et pause durable toujours ouvertes |
| 3 à 7 | À faire | Suivre `roadmap.md` ; aucune exécution Claude réelle dans ce lot |

Le socle se développe hors ligne pendant que la validation opérationnelle du
jalon 0 reste ouverte. Le chemin d'exécution abonnement ne sera pas activé avant
cette validation. Aucune fixture synthétique ne vaut preuve d'un appel réel.

## Points de retour

| Repère | Révision | Contenu | Validation |
| --- | --- | --- | --- |
| CP-000 | `ad0992b` | README et roadmap d'origine | Arbre Git propre avant implémentation |
| CP-001 | `0fdce5a` | Contrat externe et protocole de suivi | Sources officielles relues, limites locales consignées |
| CP-002 | `26469a7` | Packaging verrouillé, YAML sûr, configuration et modèles | 31 tests ciblés configuration/modèles, Ruff et mypy |
| CP-003 | `dbcb978` | Migration SQLite initiale, import atomique, ordre priorité/arrivée et lecture seule | 9 tests de file : concurrence d'import, rollback de lot, autorisation et conservation des états |
| CP-004 | `9dcefaf` | Diagnostic sans inférence, import/liste, `run --dry-run` et JSON | 10 tests CLI ; 50 tests au total, paquet construit |
| CP-005 | `425075f` | CI Python 3.11/3.13, conventions et documentation des commandes disponibles | Actions épinglées par SHA ; 50 tests locaux sur les deux versions et smoke CLI en processus séparés |
| CP-006 | `e3f7f88` | Correction du constat P2 des revues Standards et Spec : chemins SQLite imbriqués et parent fichier refusés | 55 tests sur Python 3.11 ; correction confirmée par les deux revues |
| CP-007 | `ae1ecf7` | Socle Python documenté, point de départ du jalon 2 | Arbre propre à la reprise ; PR #1 ouverte |
| CP-008 | `552e051` | Classification conservatrice du JSON terminal, usage inconnu et diagnostics expurgés | 36 tests de résultats, fixtures synthétiques et credentials factices |
| CP-009 | `ecb3b67` | stdin littéral, sorties séparées, délais, limites de sortie et arrêt des descendants | Tests POSIX, enfant ignorant SIGTERM, parent terminé et interruption clavier ; correctif macOS CP-011 nécessaire |
| CP-010 | `819261c` | Interface ClaudeRunner, faux déterministe et précontrôles avant une seule invocation | 28 tests sur faux CLI local ; refus d'environnement incompatible, version différente et compte non confirmé |
| CP-011 | `f352270` | Cas macOS EPERM sur groupe terminé : interruption initiale préservée, refus sur processus vivant conservé | Régression simulée et vraie interruption ; suite complète et build relancés |
| CP-012 | `3cba885` | Corrections des revues : credentials cités/échappés et champs inconnus ; fins interrompues refusées | Régressions sur sérialisation complète, espaces, JSON tronqué et métadonnées reconnues |
| CP-013 | `7195818` | Décodeur JSON unique, doublons refusés avant expurgation, credentials multilignes supprimés | 156 tests, Ruff, mypy et build ; constats Standards et Spec revérifiés et fermés |
| CP-014 | `0342492` | Convention de référence locale au gestionnaire de credentials, exemple sans secret et livraison exécuteur | `.env` ignoré par Git et permissions locales 0600 ; aucune clé dans les fichiers suivis |
| CP-015 | `f887f88` | Dernière révision de la PR #2, avant nouveau cadrage | Point de retour du nom et de l'ancien parcours abonnement |
| CP-016 | Commit `refactor!: rename package and CLI to token_maxxxer` | Nom cohérent du paquet, commande, exemples, stockage par défaut et références publiques | Suite existante et outils de qualité après renommage |
| CP-017 | Commit `feat(api): add Claude and OpenAI providers with private credentials` | Interface Provider, SDK API, query explicite, doctor sans CLI, références de credentials résolues à la demande | Transports HTTP simulés, limites, erreurs sans relance, clés absentes et diagnostic sans lecture de secret |

## Livraison du socle

- Branche : `feat/python-foundation`.
- PR : [#1 — socle Python hors ligne](https://github.com/speillet/token_maxxxer/pull/1).
- Validation locale : 55 tests sous Python 3.11 ; les 50 tests du lot initial
  passaient aussi sous Python 3.13. Ruff, format, mypy strict, sdist et wheel
  validés. Import de LangGraph, LangChain Core et `SqliteSaver` vérifié.
- Smoke CLI en processus séparés : import, réimport, liste, simulation et
  diagnostic ; tâche toujours `pending`, état Git inchangé, stockage temporaire.
- Revue Standards : 1 constat P2, corrigé dans CP-006 et revérifié ; 0 ouvert.
- Revue Spec : 1 constat P2, corrigé dans CP-006 et revérifié ; 0 ouvert.
- CI distante : matrice macOS/Linux et Python 3.11/3.13 ; consulter les checks de
  la PR pour le résultat attaché à la dernière révision.

Chaque livraison ajoute ici son périmètre, ses vérifications et le nom du commit.
Pour retrouver son SHA : `git log --oneline --all`. Les commits portent une seule
responsabilité et utilisent Conventional Commits.

## Livraison de l'exécuteur hors ligne

- Branche : `feat/claude-runner`, basée sur la PR #1 encore ouverte.
- PR : [#2 — transport CLI qualifié et tests hors ligne](https://github.com/speillet/token_maxxxer/pull/2).
- 156 tests sous Python 3.11 et 3.13 sur macOS ; Ruff, typage strict et
  construction sdist/wheel validés. CI macOS/Linux attachée à la dernière révision de la PR.
- Revue Standards : corrections des credentials échappés/dupliqués et du schéma
  strict vérifiées ; aucun constat ouvert sur ce périmètre.
- Revue Spec : correction des diagnostics expurgés vérifiée ; aucun constat ouvert.
- Limites : CLI réel et pilote abonnement non qualifiés, pause durable et
  gestionnaire SIGTERM du superviseur à raccorder avant activation/service.
- Données locales : `.env` contient uniquement une référence, avec permissions
  0600 ; le secret réside dans le gestionnaire de credentials du système. Aucun
  chargement de `.env` ni appel API n'est activé dans le mode abonnement.

## Retour arrière

Pour inspecter un point sans toucher au travail courant :

```bash
git worktree add --detach ../token_maxxxer-cp000 ad0992b
```

Pour annuler un commit publié, créer une branche puis un commit inverse avec
`git revert <sha>`, lancer les vérifications et ouvrir une PR. Annuler les commits
dépendants du plus récent au plus ancien. Conserver l'historique partagé.

Les données locales (`var/`, worktrees, rapports) sont exclues de Git : un revert
de code ne les restaure pas. Avant une migration future, arrêter le service et
effectuer une sauvegarde SQLite avec son API `backup` ; conserver aussi les
worktrees non validés. La migration initiale n'a pas de downgrade destructif.
Le rollback Git ne modifie ni `.env` ni le trousseau système ; gérer séparément
ces données locales si leur suppression ou leur rotation est nécessaire.

## Prochaine reprise

1. Consulter les PR du socle et de l'exécuteur ainsi que leurs résultats CI.
2. Installer/identifier le CLI officiel, vérifier la connexion abonnement et les
   crédits supplémentaires dans le compte, puis consigner un appel minimal.
3. Préparer le jalon 3 : worktree Git autorisé, audit, vérifications ; raccorder
   ensuite la commande réelle seulement si la qualification du jalon 0 est acquise.
4. Ajouter la pause durable d'authentification avec le workflow du jalon 4.
