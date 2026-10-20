-- Sofa: open the Sofa web app on this Mac (Firefox if installed, otherwise the default browser).
set sofaURL to "http://localhost:8090/"
try
	do shell script "open -a Firefox " & quoted form of sofaURL
on error
	open location sofaURL
end try
