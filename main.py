# Game Flow
import server.server as server

# For testing purposes only

if __name__ == "__main__":
    print("Starting Server")
    host = "127.0.0.1"
    port = 8000    
    server.start_server(host, port)

    