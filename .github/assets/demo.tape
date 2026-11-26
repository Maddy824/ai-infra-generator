# Records .github/assets/demo.gif, the clip at the top of the README.
# Needs vhs (https://github.com/charmbracelet/vhs) and ai-infra on PATH (pip install -e ./ai-infra).
# Run from the repository root: vhs .github/assets/demo.tape
# It works on a fresh copy of the example in /tmp, so the repository is not changed.

Output .github/assets/demo.gif
Set Shell "bash"
Set FontSize 17
Set Width 1240
Set Height 640
Set Padding 28
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set WindowBar Colorful
Set CursorBlink false

Hide
Type "rm -rf /tmp/ai-infra-generator && mkdir -p /tmp/ai-infra-generator && cp -R examples /tmp/ai-infra-generator/ && rm -rf /tmp/ai-infra-generator/examples/*/generated && cd /tmp/ai-infra-generator && export PS1='\[\e[1;32m\]$ \[\e[0m\]' && clear"
Enter
Sleep 800ms
Show

Sleep 400ms
Type "ai-infra run examples/flask-postgres --offline"
Sleep 400ms
Enter
Sleep 3.5s
Type "head -12 examples/flask-postgres/docker-compose.yml"
Sleep 300ms
Enter
Sleep 4s
