.PHONY: help setup map map-secondary transactions floor-areas prices periods inequality test all lint clean

help:
	@echo "setup          install dependencies"
	@echo "map            render the primary catchment map (needs the missing .shp)"
	@echo "map-secondary  render the secondary catchment stand-in"
	@echo "transactions   locate Price Paid sales and assign them to catchments"
	@echo "floor-areas    attach EPC floor areas (slow: scans the EPC archive)"
	@echo "prices         per-catchment table and choropleths"
	@echo "periods        distribution, rank shift and outsized-mover figures"
	@echo "inequality     within-catchment inequality and adjacent rich/poor divides"
	@echo "all            the full pipeline, in order"
	@echo "test           pytest"
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

transactions:
	uv run python scripts/build_transactions.py --layer secondary --years 20

floor-areas:
	uv run python scripts/build_floor_areas.py --layer secondary

prices:
	uv run python scripts/summarise_prices.py --layer secondary

periods:
	uv run python scripts/compare_periods.py --layer secondary

inequality:
	uv run python scripts/analyse_inequality.py --layer secondary

test:
	uv run pytest tests -q

all: transactions floor-areas prices periods inequality map-secondary
