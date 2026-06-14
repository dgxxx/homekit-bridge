default: help
project = $(notdir $(CURDIR))
.PHONY: stop
.PHONY: start
.PHONY: restart
.PHONY: console
.PHONY: logs
.PHONY: report
.PHONY: buildstart
.PHONY: buildrestart

help:
	@echo "Makefile for the $(project) project"
	@echo ""
	@echo "available options:"
	@echo " start         - start container"
	@echo " stop          - stop congainer"
	@echo " restart       - restart congainer"
	@echo " console       - open container console "
	@echo " logs          - open container console "
	@echo " report        - update electricity report webpage "
	@echo " realoadconfig - reload prometheus config "

start:
	@echo "Starting container $(project)"
	@docker-compose  --file $(project).yaml --project-name $(project) up -d

stop:
	@echo "Stopping container $(project)"
	@docker-compose --file $(project).yaml  --project-name $(project) down
restart:
	
	@echo "Stopping container $(project)"
	@docker-compose --file $(project).yaml  --project-name $(project) down
	@echo "Starting container $(project)"
	@docker-compose  --file $(project).yaml --project-name $(project) up -d

console:
	@echo "Starting console for container $(project)"
	@docker exec -it $(project) sh

logs:	
	@echo "Showing logs for  container $(project)"
	@docker logs -f $(project)

buildstart: 
	@echo "Buildingg container $(project)"
	@docker rmi $(project)_$(project)
	@docker-compose  --file $(project).yaml --project-name $(project) up -d --build

buildrestart: 
	@echo "Stopping container $(project)"
	@docker-compose --file $(project).yaml  --project-name $(project) down
	@echo "Buildingg container $(project)"
	@docker rmi $(project)_$(project)
	@docker-compose  --file $(project).yaml --project-name $(project) up -d --build
