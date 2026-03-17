SHELL := /bin/bash

.PHONY: help ca broker client up down
help:
	@echo "make ca             # create CA (certs/ca)"
	@echo "make broker         # create broker cert signed by CA (certs/broker)"
	@echo "make client CN=...  # create client cert with CN (certs/clients/<CN>)"
	@echo "make up             # start mosquitto (TLS 8883)"
	@echo "make down           # stop mosquitto"

ca:
	./scripts/pki/make-ca.sh

broker: ca
	./scripts/pki/make-broker.sh

client: ca
	@if [ -z "$$CN" ]; then echo "CN required: make client CN=sensor-h2_purity-03"; exit 1; fi
	./scripts/pki/make-client.sh "$$CN"
	@echo "Add an ACL entry for $$CN in mosquitto/conf/aclfile"

up:
	docker compose up -d --remove-orphans

down:
	docker compose down

sim:
	python3 -m venv .venv && . .venv/bin/activate && \
	pip install -r clients/python/requirements.txt && \
	python clients/python/publisher.py

sim_plant:
	python3 -m venv .venv && . .venv/bin/activate && \
	pip install -r clients/python/requirements.txt && \
	python clients/python/plant_sim.py

test:
	python3 -m venv .venv && . .venv/bin/activate && \
	pip install jsonschema pytest && pytest -q
