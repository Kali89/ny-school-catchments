.PHONY: help setup map map-secondary lint clean

help:
	@echo "setup          install dependencies"
	@echo "map            render the primary catchment map (needs the missing .shp)"
	@echo "map-secondary  render the secondary catchment stand-in"
	@echo "lint           ruff check"
	@echo "clean          remove generated figures"

setup:
	uv sync

map:
	uv run python scripts/make_map.py --layer primary

map-secondary:
	uv run python scripts/make_map.py --layer secondary

lint:
	uv run ruff check src scripts

clean:
	rm -f outputs/*.png
