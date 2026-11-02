# Roadmap — token_maxxxer

Cadrage actualisé le 2 novembre 2026 : le dépôt s'appelle `token_maxxxer` et
utilise des clés API. Claude est le premier fournisseur ; OpenAI partage le
même contrat ; GitHub Copilot sera ajouté via son SDK et son authentification
GitHub. Ce cadrage remplace la dépendance initiale à un abonnement Claude Pro.
Historique, validations et rollbacks : [checkpoint.md](checkpoint.md).

## 0 — Contrats fournisseurs et accès

- [x] Documenter les API officielles Claude Messages et OpenAI Responses.
- [x] Définir un port Provider indépendant du fournisseur et des résultats normalisés.
- [x] Définir les références privées de credentials et le diagnostic sans réseau.
- [ ] Qualifier les appels réels avec des clés renouvelées et des modèles autorisés.
- [ ] Qualifier Copilot : SDK officiel, token GitHub autorisé et droits du compte.

Les transports simulés permettent de développer sans appel facturé. Ils ne
valident pas les droits, limites ou coûts d'un compte réel.

## 1 — Socle Python

- [x] Paquet, commande, imports et exemples nommés `token_maxxxer`.
- [x] Dépendances verrouillées, modèles et configuration validés.
- [x] Import YAML idempotent et atomique, ordre priorité puis arrivée.
- [x] Migration initiale SQLite et séparation des bases applicative/checkpoints.
- [x] Doctor, liste et simulation sans effet sur la file ou les dépôts.
- [x] Ruff, typage strict, tests et CI macOS/Linux.

## 2 — Adaptateurs de génération API

- [x] Claude : SDK officiel avec clé API, consigne texte et tokens observés.
- [x] OpenAI : Responses API via SDK officiel, sans stockage demandé de la réponse.
- [x] Une commande query explicite, sans exécution locale ni mutation de tâche.
- [x] Timeout HTTP, plafond de sortie et aucune relance automatique.
- [x] Classification auth, quota, timeout, réseau et résultat incomplet.
- [x] Références Trousseau macOS, variables d'environnement et diagnostics expurgés.
- [x] Tests HTTP simulés, aucune requête réelle dans la suite.
- [ ] Ajouter l'adaptateur GitHub Copilot derrière le même port.

Une génération terminée ne vaut pas tâche de développement vérifiée. Les
paramètres du modèle sont explicites et aucun fournisseur de secours n'est choisi.

## 3 — Agent de code, Git et vérification

- [ ] Construire la boucle d'outils typés autour du fournisseur choisi.
- [ ] Limiter lecture, écriture et commandes aux opérations explicitement approuvées.
- [ ] Préparer un worktree et une branche stables depuis une base Git explicite.
- [ ] Préserver l'arbre principal et refuser les collisions.
- [ ] Exécuter les vérifications configurées avec timeout et journaux séparés.
- [ ] Conserver le diff, les échecs et les travaux non validés.
- [ ] Utiliser needs_review si des critères restent humains ; aucun merge automatique.
- [ ] Raccorder run --once seulement après ces contrôles et un pilote réversible.

## 4 — Workflow durable et reprise

- [ ] Nœuds LangGraph déterministes : sélection, préparation, exécution, vérification, classement et rapport.
- [ ] Checkpointer SQLite, thread stable et version du schéma d'état.
- [ ] Journal de tentative avant chaque effet externe et résultat durable dès réception.
- [ ] Acquisition atomique, verrou local et commandes pause/reprise/annulation.
- [ ] Auth expirée mise en pause ; reprise d'une tâche ambiguë soumise à revue.
- [ ] Tests de crash avant, pendant et après le résultat ; aucun double lancement observé.

## 5 — Planning, quotas et budgets

- [ ] Fenêtres IANA semi-ouvertes avec minuit, fusion des chevauchements et changements d'heure.
- [ ] Contrôle avant lancement et watchdog jusqu'à la fermeture, grâce comprise.
- [ ] Pause sur quota avec reprise fiable ou backoff borné, sans rafale.
- [ ] Persist next_retry_at et compteurs ; aucun reset des plafonds au redémarrage.
- [ ] Temps actif et budgets API configurables, avec incertitudes de coût explicites.
- [ ] Gestion des arrêts du superviseur et de ses sous-processus.

## 6 — Services et rapports

- [ ] launchd utilisateur et systemd --user avec environnement explicite.
- [ ] Résolution des credentials sans interaction silencieuse en arrière-plan.
- [ ] Installation, démarrage, arrêt et désinstallation propres.
- [ ] Rapports Markdown et logs JSONL avec rotation et contrôle des secrets.
- [ ] Documenter veille/réveil et conserver tous les travaux non validés.

## 7 — Pilote et version 0.1

- [ ] Tâche simple dans un dépôt de démonstration, puis courte fenêtre planifiée.
- [ ] Trois tâches indépendantes : réussite, vérification en échec et reprise.
- [ ] Simuler quota, réseau, auth expirée, arrêt/redémarrage et veille/réveil.
- [ ] Valider macOS/Linux, résultats vérifiables, absence de duplication et consommation expliquée.
- [ ] Publier une version locale 0.1 après validation du MVP complet.

## Après le MVP

- [ ] Issues GitHub explicitement sélectionnées, déduplication et dépendances.
- [ ] Estimation de taille et sélection des tâches adaptées au créneau.
- [ ] Tableau de bord local et estimation de réserve avec incertitudes.
- [ ] PR optionnelles à partir de résultats validés.
- [ ] Concurrence seulement après mesure de son utilité et gestion des conflits.
