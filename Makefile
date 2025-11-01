SERVICE_NAME=mfc_daemon.service
SERVICE_FILE=$(CURDIR)/systemd/system/$(SERVICE_NAME)
SYSTEMD_DIR=/etc/systemd/system

.PHONY: all install-service uninstall-service start-service stop-service status-service clean

all: install-service

install-service:
	@echo "Installing $(SERVICE_NAME)..."
	@# Create mfc-daemon group if it doesn't exist
	@getent group mfc-daemon >/dev/null || sudo groupadd mfc-daemon
	@sudo cp $(SERVICE_FILE) $(SYSTEMD_DIR)/
	@sudo systemctl daemon-reload
	@sudo systemctl enable $(SERVICE_NAME)
	@echo "$(SERVICE_NAME) installed. Run 'make start-service' to start it."

uninstall-service:
	@echo "Uninstalling $(SERVICE_NAME)..."
	@sudo systemctl stop $(SERVICE_NAME) || true
	@sudo systemctl disable $(SERVICE_NAME) || true
	@sudo rm -f $(SYSTEMD_DIR)/$(SERVICE_NAME)
	@sudo systemctl daemon-reload
	@echo "$(SERVICE_NAME) uninstalled."

start-service:
	@echo "Starting $(SERVICE_NAME)..."
	@sudo systemctl start $(SERVICE_NAME)
	@sudo systemctl status $(SERVICE_NAME)

stop-service:
	@echo "Stopping $(SERVICE_NAME)..."
	@sudo systemctl stop $(SERVICE_NAME)
	@sudo systemctl status $(SERVICE_NAME)

status-service:
	@echo "Status of $(SERVICE_NAME):"
	@sudo systemctl status $(SERVICE_NAME)

clean:
	@echo "Cleaning up..."
	@# Add any other cleanup steps here, e.g., removing temporary files
