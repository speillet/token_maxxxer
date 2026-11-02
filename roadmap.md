# Roadmap — Claude Nightshift

**Statut : socle Python livré et testé hors ligne ; jalon 0 opérationnel ouvert.**
Document compagnon du [readme.md](readme.md). Les cases cochées indiquent les
travaux vérifiés ; preuves et retours arrière dans [checkpoint.md](checkpoint.md).
L'exécuteur Claude, le workflow durable et le planning restent à implémenter.

## Stratégie de réalisation

Construire d'abord une exécution manuelle fiable, puis la persistance, les quotas, le planning et enfin le service système. Développer chaque jalon dans une branche courte et le valider avant de poursuivre. Un faux exécuteur Claude permet de tester les erreurs et limites sans consommer l'abonnement.

Le MVP reçoit des tâches explicites, travaille sur un seul dépôt à la fois et conserve les résultats localement. La première exécution réelle est une tâche petite, réversible et vérifiable dans un dépôt de démonstration.

## Vue d'ensemble

| Jalon | Priorité | Dépendance | Livrable |
| --- | --- | --- | --- |
| 0. Faisabilité abonnement | P0 | Aucune | Contrat CLI et décision de poursuite |
| 1. Socle Python | P0 | 0 | Configuration, modèles et commandes de base |
| 2. Exécuteur Claude | P0 | 1 | Une tâche manuelle et un résultat normalisé |
| 3. Git et vérification | P0 | 2 | Travail isolé et résultat contrôlé |
| 4. LangGraph et reprise | P0 | 3 | Workflow durable et file persistante |
| 5. Quotas et planning | P0 | 4 | Exécution dans les créneaux et pauses fiables |
| 6. Services et rapports | P0 | 5 | MVP utilisable sur Mac et Linux |
| 7. Pilote et stabilisation | P0 | 6 | Version 0.1 validée en conditions réelles |
| 8. Optimisation | P1/P2 | 7 | Réserve estimée, sources de tâches et tableau de bord |

## Jalon 0 — Valider l'accès Claude Pro

- [ ] Vérifier les conditions actuelles de l'usage personnel automatisé via le CLI officiel et l'allocation réellement utilisée.
- [ ] Installer Claude Code sur la machine de développement et consigner sa version.
- [ ] Se connecter via le flux officiel ; vérifier les configurations API et fournisseurs tiers.
- [ ] Vérifier dans le compte que les crédits supplémentaires payants sont désactivés.
- [ ] Exécuter un appel non interactif minimal et examiner sa sortie structurée.
- [ ] Déterminer les options compatibles avec la version retenue : permissions, format de sortie, limitation des tours, reprise de session.
- [ ] Documenter les signaux disponibles pour succès, limite, authentification et erreur transitoire ; ne pas épuiser volontairement le quota pour les obtenir.
- [ ] Vérifier l'existence éventuelle d'une interface officielle pour le quota restant ; sinon inscrire « indisponible » dans le contrat.

**Livrable :** `docs/claude-cli-contract.md`, fixtures anonymisées et version compatible.

État actuel : [contrat documentaire](docs/claude-cli-contract.md) rédigé à partir
des sources officielles du 2 novembre 2026. CLI absent sur la machine de
développement ; version, compte, crédits supplémentaires et appel réel restent
à qualifier. Aucune fixture observée n'est disponible. Le socle est développé
hors ligne sans activer le chemin abonnement pendant cette validation.

**Validation :** un appel CLI fonctionne avec l'abonnement ; aucun appel API distinct ni extraction de jeton n'est requis. Si cette hypothèse échoue, arrêter le chemin abonnement et réviser le projet avant tout choix payant.

## Jalon 1 — Préparer le socle Python

- [x] Initialiser `pyproject.toml`, l'environnement et un fichier de dépendances verrouillé.
- [x] Ajouter LangGraph, LangChain Core, le checkpointer SQLite compatible, Pydantic, YAML et une bibliothèque CLI si utile.
- [ ] Créer les modules décrits dans le README. Le socle crée `config`, `models`, `storage`, `queue`, `doctor`, `yaml_io` et `cli` ; les modules d'exécution seront ajoutés à leur jalon, sans interfaces vides.
- [x] Définir les modèles `Task`, `Attempt`, `ExecutionState` et `UsageObservation`.
- [x] Valider les chemins, fuseaux, créneaux, bornes de reprise et identifiants de tâches.
- [x] Implémenter `doctor`, l'import YAML, la liste des tâches et `--dry-run`.
- [x] Définir la migration initiale SQLite et exclure `var/`, secrets et worktrees du suivi Git.
- [x] Configurer lint et tests ciblés en CI.

**Validation :** configuration invalide rejetée avec un message précis ; import répété sans doublon ; dry-run sans lancement Claude ni mutation du dépôt.

## Jalon 2 — Construire l'exécuteur Claude Code

- [ ] Créer une interface `ClaudeRunner` avec une implémentation réelle et une fausse implémentation déterministe.
- [ ] Lancer le CLI avec `subprocess`, des arguments séparés et sans `shell=True`.
- [ ] Fournir la consigne via un canal compatible avec le CLI, sans interpolation shell.
- [ ] Capturer stdout, stderr, code de sortie et éventuel identifiant de session.
- [ ] Normaliser les résultats : `success`, `rate_limited`, `auth_error`, `timeout`, `transient_error`, `invalid_output`.
- [ ] Distinguer absence d'une donnée d'usage et consommation nulle.
- [ ] Appliquer permissions explicites, délai maximal et arrêt du groupe de processus.
- [ ] Mettre en pause sur authentification expirée ; ne pas traiter ce cas comme un quota.
- [ ] Tester sorties malformées, erreurs internes malgré une sortie JSON, crash et processus enfant bloqué.

**Validation :** chaque scénario produit un résultat classé ; un timeout ne laisse aucun processus enfant actif ; aucune relance infinie.

## Jalon 3 — Isoler le code et vérifier le résultat

- [ ] Autoriser explicitement les dépôts utilisables.
- [ ] Enregistrer le commit de base et créer une branche/worktree stable par tâche.
- [ ] Vérifier hooks, MCP et configurations du dépôt avant de lancer le CLI non interactif.
- [ ] Préserver l'arbre de travail principal et refuser les collisions de branches ou chemins.
- [ ] Exécuter les commandes de vérification configurées avec délai et journaux séparés.
- [ ] Conserver diff, statut Git et résultats de tests, même après un échec.
- [ ] Passer en `needs_review` si les critères ne sont pas vérifiables automatiquement.
- [ ] Définir un nettoyage qui ne supprime jamais un travail non validé.

**Validation :** une tâche de démonstration produit un diff et des tests exploitables dans son worktree ; un test en échec empêche le statut `succeeded` ; aucun merge automatique.

## Jalon 4 — Implémenter LangGraph et la reprise durable

- [ ] Définir les nœuds : sélection, préparation, exécution, vérification, classement, rapport.
- [ ] Ajouter le checkpointer SQLite avec un `thread_id` stable et une version de schéma d'état.
- [ ] Utiliser des outils LangChain typés pour les opérations du projet ; conserver le routage déterministe dans LangGraph.
- [ ] Persister les tentatives avant lancement d'un effet externe et enregistrer leurs résultats dès réception.
- [ ] Acquérir les tâches atomiquement et ajouter un verrou de service local.
- [ ] Définir les transitions autorisées et les commandes pause/reprise/annulation.
- [ ] Au redémarrage, rapprocher journal, tentative et processus ; une exécution ambiguë exige une revue.
- [ ] Reprendre une session Claude seulement si le contrat CLI et l'état du worktree le permettent.
- [ ] Tester un arrêt avant lancement, pendant exécution et après résultat mais avant checkpoint.

**Validation :** aucun double lancement dans les scénarios testés ; une tâche terminée ne recommence pas ; une tâche ambiguë est conservée et signalée. Ne pas prétendre garantir une exécution « exactement une fois » d'un processus externe.

## Jalon 5 — Ajouter planning et régulation

- [ ] Implémenter des fenêtres horaires avec `zoneinfo`, timestamps UTC et jours de début explicites.
- [ ] Couvrir minuit, chevauchements, bornes et changements d'heure de Paris.
- [ ] Réévaluer le planning après réveil de la machine ou déplacement d'horloge.
- [ ] Vérifier le créneau avant chaque lancement et maintenir un watchdog jusqu'à la fin.
- [ ] Implémenter l'arrêt strict avec délai de grâce intégré au créneau.
- [ ] Sur limite, utiliser une réinitialisation fiable lorsqu'elle existe, sinon un backoff borné avec léger jitter.
- [ ] Persister `next_retry_at` et les compteurs : un redémarrage ne remet pas les limites de reprise à zéro.
- [ ] Séparer pauses quota, erreurs transitoires et échecs métier ; prévoir un plafond de relances par fenêtre.
- [ ] Suspendre les tentatives lorsque les plafonds sont atteints et les rendre visibles dans le rapport.
- [ ] Implémenter le plafond de temps actif sans le présenter comme une réserve exacte de quota.

**Validation :** tests avec horloge simulée ; aucun lancement hors créneau ; arrêt local à l'échéance ; une réponse de quota n'entraîne pas de rafale ; une date de reprise située hors créneau est reportée à la prochaine fenêtre autorisée.

## Jalon 6 — Livrer le service Mac/Linux et les rapports

- [ ] Créer un service `launchd` utilisateur et un service `systemd --user`.
- [ ] Utiliser chemins absolus, répertoire de travail et environnement explicites.
- [ ] Tester l'accès à l'authentification depuis une session non interactive, notamment le trousseau macOS.
- [ ] Fournir installation, démarrage, arrêt, désinstallation et inspection des logs.
- [ ] Documenter les limites d'un ordinateur en veille et le comportement après réveil ; ne pas modifier automatiquement ses réglages d'énergie.
- [ ] Produire un rapport Markdown par fenêtre et un journal JSONL avec rotation.
- [ ] Afficher tâches validées, branches, tests, pauses, erreurs et usage observé ou inconnu.
- [ ] Vérifier la suppression des secrets dans les logs et rapports.

**Validation :** démarrage et arrêt propres sur les deux OS ; service unique ; résultats consultables sans ouvrir SQLite ; aucune authentification interactive demandée silencieusement en arrière-plan.

## Jalon 7 — Valider le MVP en conditions réelles

- [ ] Exécuter une tâche simple manuellement sur un dépôt de démonstration.
- [ ] Exécuter une courte fenêtre planifiée avec une seule tâche.
- [ ] Tester une file de trois tâches indépendantes : réussite, vérification en échec et reprise.
- [ ] Simuler quota, panne réseau et authentification expirée.
- [ ] Tester arrêt/redémarrage du service et mise en veille/réveil.
- [ ] Répéter un pilote sur plusieurs créneaux et comparer résultats utiles, temps actif et interventions.
- [ ] Corriger les défauts observés ; documenter les limites connues.
- [ ] Mettre à jour le README avec les commandes réellement implémentées et publier une version locale `0.1`.

**Définition de terminé :** tâches planifiées, résultats vérifiés, reprise sans duplication observée, quotas respectés, travail conservé, absence de bascule de facturation dans le parcours testé, fonctionnement validé sous macOS et Linux.

## Après le MVP

### P1 — Améliorer l'utilité

- [ ] Import d'issues GitHub explicitement sélectionnées et déduplication par identifiant.
- [ ] Dépendances entre tâches avec propagation contrôlée des commits.
- [ ] Estimation de taille des tâches et choix de celles qui tiennent dans le créneau.
- [ ] Mode de réserve pour l'usage en journée, affichant clairement les incertitudes.
- [ ] Détection des changements de version du CLI et tests de compatibilité.
- [ ] Tableau de bord local en lecture seule.

### P2 — Étendre l'autonomie

- [ ] Audit de dépôt qui propose des tâches à approuver avant exécution.
- [ ] Création optionnelle de PR à partir de résultats validés.
- [ ] Concurrence limitée uniquement après résolution des conflits Git et mesure de son intérêt avec Pro.
- [ ] Backend API optionnel, séparé du mode abonnement, avec budget explicite.

## Décisions à confirmer avant le premier pilote

| Décision | Proposition initiale |
| --- | --- |
| Nom du projet | `claude-nightshift` |
| Premier dépôt | Dépôt de démonstration choisi par l'utilisateur |
| Première source de tâches | Fichier YAML explicite |
| Créneaux | Tous les jours, 22 h–7 h, Europe/Paris |
| Fin de créneau | Arrêt strict et conservation du travail |
| Consommation nocturne | Une tâche à la fois, plafond de temps configurable |
| Résultats | Branches et rapports locaux, revue avant intégration |

Ces valeurs sont des hypothèses de développement et restent configurables. Aucun calendrier de livraison n'est engagé : chaque jalon est accepté sur ses critères de validation.
