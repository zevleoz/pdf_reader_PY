import os
import signal
import subprocess
import time

def kill_port_5000():
    try:
        result = subprocess.run(['lsof', '-ti', ':5000'], capture_output=True, text=True)
        pids = result.stdout.strip().split('\n')
        for pid in pids:
            if pid:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    print(f"Killed process {pid}")
                except:
                    pass
    except:
        pass

def start_server():
    os.chdir('/Users/jefflau/projects/pdf_report_converter/PDF_converter')
    subprocess.Popen([
        '/Users/jefflau/anaconda3/bin/python3', '-m', 'http.server', '5000'
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Server started on port 5000")

if __name__ == '__main__':
    kill_port_5000()
    time.sleep(1)
    start_server()