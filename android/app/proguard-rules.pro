# WorkManager persists the worker class name across application upgrades.
-keep class io.github.nico579.watch2notif.PollWorker { public <init>(...); }
