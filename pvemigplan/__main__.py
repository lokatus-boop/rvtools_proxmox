import sys

# Sin argumentos (o solo un proyecto .pveplan, p. ej. al hacer doble clic en él) se abre la interfaz gráfica.
if len(sys.argv) > 1 and not (len(sys.argv) == 2 and sys.argv[1].lower().endswith(".pveplan")):
    from .cli import main
else:
    from .gui import main

sys.exit(main())
