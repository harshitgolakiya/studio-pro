"""App-facing bridges to SDK exporters and conversion lifecycle hooks."""
from pathlib import Path


def load_plugins():
    from plugin_sdk import get_registry, discover_plugins
    registry = get_registry()
    # Reload into the same registry, so new callbacks don't multiply on every click.
    registry.codecs.clear()
    registry.processors.clear()
    registry.exporters.clear()
    registry._hooks.clear()
    discover_plugins(registry)
    return {"codecs": [p.name for p in registry.codecs], "processors": [p.name for p in registry.processors],
            "exporters": [p.name for p in registry.exporters], "hooks": list(registry._hooks)}


def before_conversion(source, settings):
    from workflow_hooks import get_hook_manager
    from plugin_sdk import get_registry
    if get_hook_manager().enabled:
        get_hook_manager().fire_before_convert(source, dict(settings))
        get_registry().fire_hook("before_convert", source, dict(settings))


def after_conversion(source, result):
    from workflow_hooks import get_hook_manager
    from plugin_sdk import get_registry
    if get_hook_manager().enabled:
        get_hook_manager().fire_after_convert(source, result.output_path, result.status)
        get_registry().fire_hook("after_convert", source, result)
        if result.status == "Failed":
            error = RuntimeError(result.error or "Conversion failed")
            get_hook_manager().fire_on_error(source, error)
            get_registry().fire_hook("on_error", source, error)


def batch_event(event, sources=None, settings=None, results=None):
    from workflow_hooks import get_hook_manager
    from plugin_sdk import get_registry
    manager = get_hook_manager()
    if not manager.enabled:
        return
    if event == "before_batch":
        manager.fire_before_batch([str(p) for p in sources], settings or {})
        get_registry().fire_hook(event, sources, settings or {})
    else:
        manager.fire_after_batch([{"source": str(r.source_path), "status": r.status} for r in results])
        get_registry().fire_hook(event, results)


def publish_file(adapter, source, config):
    from integrations import LocalWebProjectIntegration, CloudStorageIntegration, WordPressIntegration, DesignToolWatchIntegration
    if not source.is_file():
        raise ValueError("Choose an existing file to publish")
    if adapter == "Plugin exporter":
        from plugin_sdk import get_registry
        exporter = next((p for p in get_registry().exporters if p.name == config.get("name")), None)
        if not exporter:
            raise ValueError("Load plugins and choose an installed exporter")
        return exporter.export(source, source, {})
    config = dict(config)
    if adapter == "Local web project":
        config["project_root"] = Path(config["project_root"])
        implementation = LocalWebProjectIntegration(**config)
        asset_path = (implementation.project_root / implementation.assets_dir).resolve()
        if not asset_path.is_relative_to(implementation.project_root.resolve()):
            raise ValueError("Assets subfolder must stay inside the web project")
    elif adapter == "Cloud storage":
        implementation = CloudStorageIntegration(**config)
    elif adapter == "WordPress":
        implementation = WordPressIntegration(**config)
    elif adapter == "Design export folder":
        config["output_dir"] = Path(config["output_dir"])
        config["watch_dir"] = source.parent
        implementation = DesignToolWatchIntegration(**config)
    else:
        raise ValueError("Unknown publishing adapter")
    errors = implementation.validate_config()
    if errors:
        raise ValueError("; ".join(errors))
    return implementation.publish(source, source, {})
