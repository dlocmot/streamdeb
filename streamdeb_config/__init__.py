"""streamdeb_config — GUI configurador GTK4 para streamdeb.

Edita `~/.config/streamdeb/config.toml`. El servicio streamdeb detecta el
cambio vía polling de mtime cada 2s y recarga los plugins editables sin
restart (apps, web, keys, vent).
"""
__version__ = "0.1.0"
