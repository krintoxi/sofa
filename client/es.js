/* Sofa in Spanish.

   Loaded only when this device asks for Spanish (index.html: the language chosen under Theme, else the device's own),
   before app.js. The app's pages are written in English; this file puts what they draw into Spanish as it's drawn:
   text, placeholders, labels and tooltips, the browser's own question boxes, and dates. Nothing here runs in English.

   Covered: the header and menus, Home, Shows, Movies, a title's page and its file's details, search, My List, More,
   sign-in, Who's watching,
   Theme, Play on, downloads, and the player with its menus. Not yet: the Server pages, Live TV's guide and recordings,
   Games, Music, the Adult section, watching together, and the Sofa Box's own Home and player (they're drawn elsewhere).

   How to add to it: the key is the English exactly as the page shows it. "{}" stands for anything the page fills in (a
   name, a time), "{n}" for a number; "{1}", "{2}" put them back in the Spanish. tests/test_spanish.py fails when a key
   is no longer in client/app.js or index.html, so a change of English wording is noticed here.

   The Spanish: Latin American, "tú", plain. serie, película, temporada, episodio, Inicio, Mi lista, visto. */
(function () {
  "use strict";

  const WORDS = {
    // ---- the header and menus
    "Home": "Inicio", "Shows": "Series", "Movies": "Películas", "My List": "Mi lista", "Music": "Música",
    "Live TV": "TV en vivo", "Games": "Juegos", "Adult": "Adultos", "Server": "Servidor", "More": "Más",
    "Search": "Buscar", "Theme": "Tema", "Sign out": "Cerrar sesión", "Leave": "Salir", "Sign in": "Iniciar sesión",
    "Library": "Biblioteca", "Search shows and movies": "Busca series y películas",
    "Search shows, movies and episodes": "Busca series, películas y episodios",
    "Play on another screen": "Reproducir en otra pantalla", "Who's watching? Switch profile": "¿Quién ve? Cambiar de perfil",
    "Suggestions": "Sugerencias", "Public": "Público",
    "Use TV mode on this device": "Usar el modo TV en este dispositivo",
    "Turn off TV mode on this device": "Quitar el modo TV en este dispositivo",
    "Project by": "Un proyecto de", "About, privacy and copyright": "Acerca de, privacidad y derechos",
    "Can't reach the server": "No se puede conectar con el servidor",

    // ---- More (phones)
    "Guest": "Invitado", "Kids profile": "Perfil infantil", "Runs this Sofa": "Administra este Sofa", "Profile": "Perfil",
    "Albums, artists, stations": "Álbumes, artistas, estaciones", "Free channels": "Canales gratis",
    "Free, with a keyboard or a controller": "Gratis, con teclado o control", "About this Sofa": "Acerca de este Sofa",
    "Privacy, copyright and who to write to": "Privacidad, derechos y a quién escribir",
    "Get a Sofa Box": "Consigue una Sofa Box",
    "Your own TV box on a Raspberry Pi: Sofa, Live TV, apps and games": "Tu propia caja para la tele en una Raspberry Pi: Sofa, TV en vivo, apps y juegos",
    "Colours, subtitles, this device": "Colores, subtítulos, este dispositivo", "Pair a TV": "Vincular una tele",
    "Sign a TV in with this phone": "Inicia sesión en una tele con este teléfono", "Install Sofa": "Instalar Sofa",
    "On the home screen, like an app": "En la pantalla de inicio, como una app",
    "Library, people, internet, updates": "Biblioteca, personas, internet, actualizaciones", "Servers": "Servidores",
    "Other Sofas you watch from": "Otros Sofa que ves desde aquí",
    "Switch to another server, or add one": "Cambia de servidor o agrega uno", "This Sofa box": "Esta Sofa Box",
    "Picture, sound, Wi-Fi, controllers, apps": "Imagen, sonido, Wi-Fi, controles, apps",

    // ---- Home
    "Continue watching": "Seguir viendo", "New episodes": "Episodios nuevos", "Coming up": "Próximamente",
    "Next up": "A continuación", "Because you watched…": "Porque viste…", "Movies you haven't seen": "Películas que no has visto",
    "New movies": "Películas nuevas", "Something short": "Algo corto", "Recently added episodes": "Episodios agregados hace poco",
    "A row for each genre": "Una fila por género", "Featured banner": "Portada destacada", "Featured": "Destacado",
    "See all": "Ver todo", "Scroll left": "Ir a la izquierda", "Scroll right": "Ir a la derecha",
    "Series": "Serie", "Movie": "Película", "Continue the series": "Continúa la serie", "More info": "Más información",
    "Episodes": "Episodios", "Choose a featured title": "Elige un título destacado", "Sound": "Sonido",
    "Sound on": "Activar sonido", "Sound off": "Quitar sonido", "Play the trailer again": "Ver el tráiler otra vez",
    "Arrange Home": "Ordenar Inicio", "Sofa's own": "Como viene", "Have a look": "Revisar",
    "They're waiting for you in Server → People.": "Te esperan en Servidor → Personas.",
    "Rows with nothing in them don't show.": "Las filas vacías no se muestran.",
    "New": "Nuevo", "New episode": "Episodio nuevo", "Most episodes": "Más episodios",
    "Sofa is reading your library": "Sofa está leyendo tu biblioteca",
    "It just started. Your shows and movies appear here in a moment, by themselves.": "Acaba de empezar. Tus series y películas aparecerán aquí en un momento, solas.",
    "Nothing shared yet": "Aún no hay nada compartido", "Nothing to watch yet": "Aún no hay nada que ver",
    "Open the Server page": "Abrir la página del servidor",

    // ---- Shows and Movies
    "All": "Todo", "Genres": "Géneros", "Surprise me": "Sorpréndeme",
    "Filter by name, genre, network or year": "Filtra por nombre, género, canal o año",
    "Filter shows": "Filtrar series", "Filter movies": "Filtrar películas", "What you've watched": "Lo que has visto",
    "Not started": "Sin empezar", "Watching": "Viendo", "Watched": "Visto", "Sort shows": "Ordenar series",
    "Sort movies": "Ordenar películas", "Name": "Nombre", "Recently added": "Agregado hace poco", "Year": "Año",
    "No shows match.": "Ninguna serie coincide.", "No shows match. Try clearing the filter.": "Ninguna serie coincide. Prueba a quitar el filtro.",
    "No movies match. Try clearing the filter.": "Ninguna película coincide. Prueba a quitar el filtro.",
    "No movies yet. Drop one in the Inbox, named like \"Title (1999)\".": "Aún no hay películas. Deja una en la carpeta Inbox, con un nombre como «Título (1999)».",
    "Collections": "Colecciones", "All movies": "Todas las películas",

    // ---- a title's page
    "Play": "Reproducir", "Resume": "Continuar", "Play next": "Ver el siguiente", "Start over": "Desde el principio",
    "Mark watched": "Marcar como visto", "Mark as watched": "Marcar como visto", "Mark as not watched": "Marcar como no visto",
    "Download": "Descargar", "+ My List": "+ Mi lista", "Add to My List": "Agregar a Mi lista",
    "Remove from My List": "Quitar de Mi lista", "Find details": "Buscar detalles", "Fix details": "Corregir detalles",
    "Manage": "Administrar", "Share": "Compartir", "Shared": "Compartido", "For kids": "Para niños",
    "In the public library": "En la biblioteca pública", "Add to the public library": "Agregar a la biblioteca pública",
    "Remove from Continue watching": "Quitar de Seguir viendo", "Favorite": "Favorito", "Rated": "Calificación",
    "on TVmaze": "en TVmaze", "Seasons": "Temporadas", "Specials": "Especiales", "Extras": "Extras", "Extra": "Extra",
    "Mark all watched": "Marcar todo como visto", "Mark all not watched": "Marcar todo como no visto",
    "Manage this episode": "Administrar este episodio", "Move, delete or new picture": "Mover, borrar o cambiar la imagen",
    "Not in your library": "No están en tu biblioteca", "Untitled": "Sin título", "Licence": "Licencia", "From": "De",
    "Credit": "Crédito", "Changes": "Cambios", "today": "hoy", "tomorrow": "mañana", "just now": "ahora mismo",
    "More like this": "Más como esto", "Set by an admin": "Lo decidió un administrador",
    "From its rating and genres": "Por su clasificación y sus géneros",

    // ---- search and My List
    "Shows, movies, episodes, genres, years": "Series, películas, episodios, géneros, años",
    "Type part of a title, an episode name, a genre or a year.": "Escribe parte de un título, el nombre de un episodio, un género o un año.",
    "Nothing matches. Try part of an episode title.": "No hay coincidencias. Prueba con parte del título de un episodio.",
    "Nothing here yet. Press": "Aún no hay nada aquí. Presiona",
    "on a show or a movie (or on the card that opens when you point at one) to keep it here for later.": "en una serie o película (o en la tarjeta que se abre al señalarla) para guardarla aquí.",
    "Added to My List.": "Agregado a Mi lista.", "Removed.": "Quitado.",
    "Removed from Continue watching. It comes back when you watch it again.": "Quitado de Seguir viendo. Vuelve cuando lo veas otra vez.",
    "Nothing here to pick from.": "No hay nada para elegir aquí.",
    "That page isn't here": "Esa página no existe", "The show may have been renamed or removed.": "Puede que la serie haya cambiado de nombre o ya no esté.",
    "Go home": "Ir a Inicio",

    // ---- sign-in
    "Password": "Contraseña", "Password again": "La contraseña otra vez", "Watch as a guest": "Ver como invitado",
    "Sign in with your phone": "Iniciar sesión con tu teléfono", "New here?": "¿Eres nuevo aquí?",
    "Create an account": "Crear una cuenta", "Your name": "Tu nombre", "Who are you?": "¿Quién eres?",
    "(so they know it's you)": "(para que sepan que eres tú)", "Ask for an account": "Pedir una cuenta",
    "I have an account": "Ya tengo cuenta", "Asked": "Pedido", "Back to sign in": "Volver a iniciar sesión",
    "with your password. You could tell them it's waiting.": "con tu contraseña. Puedes avisarle que está esperando.",
    "and type the code.": "y escribe el código.", "Code": "Código",
    "The code works for 10 minutes. Waiting for your phone…": "El código sirve por 10 minutos. Esperando a tu teléfono…",
    "Use a name and password instead": "Mejor usar nombre y contraseña", "Type the code the TV shows.": "Escribe el código que muestra la tele.",
    "Next": "Siguiente", "as:": "como:", "Kids": "Niños", "You": "Tú", "Type a code": "Escribir un código",
    "Looking…": "Buscando…", "Done.": "Listo.", "The TV signs in by itself in a moment.": "La tele inicia sesión sola en un momento.",
    "Back to Home": "Volver a Inicio", "The passwords don't match.": "Las contraseñas no coinciden.",
    "The code has 6 digits.": "El código tiene 6 dígitos.", "Sign this device out?": "¿Cerrar la sesión en este dispositivo?",

    // ---- Who's watching, your profile
    "Who's watching?": "¿Quién ve?", "Locked": "Con PIN", "Watching now": "Viendo ahora",
    "Your profile: color and PIN": "Tu perfil: color y PIN", "Watch together": "Ver juntos", "Close": "Cerrar",
    "A public library: what's shared here, for anyone with the link.": "Una biblioteca pública: lo que se comparte aquí, para quien tenga el enlace.",
    "Continue": "Continuar", "Back": "Atrás", "Your profile": "Tu perfil", "Color": "Color", "New PIN": "PIN nuevo",
    "New PIN (4 digits)": "PIN nuevo (4 dígitos)", "Your password": "Tu contraseña", "Remove PIN": "Quitar el PIN",
    "PIN removed.": "PIN quitado.", "PIN saved.": "PIN guardado.", "Save": "Guardar", "Saved.": "Guardado.", "Cancel": "Cancelar",
    "OK": "Aceptar", "Open": "Abrir", "Add or change servers": "Agregar o cambiar servidores",
    "Address or share link": "Dirección o enlace compartido", "That doesn't look like an address.": "Eso no parece una dirección.",

    // ---- Theme (Look and feel)
    "Look and feel": "Apariencia", "Yours, on every screen you use. Everyone can pick their own.": "Tuya, en cada pantalla que uses. Cada quien elige la suya.",
    "Accent colour": "Color de acento", "The theme's own": "El del tema", "Any colour": "Cualquier color",
    "Animations": "Animaciones", "Lively": "Animadas", "Calm": "Tranquilas", "Off": "No", "Loading screen": "Pantalla de carga",
    "Sofa's": "La de Sofa", "Quick": "Rápida", "None": "Ninguna", "Subtitle size": "Tamaño de los subtítulos",
    "Small": "Chico", "Medium": "Medio", "Large": "Grande", "Huge": "Enorme", "Arrange": "Ordenar",
    "What's on Home": "Qué hay en Inicio", "Which rows, in which order. Yours on every screen.": "Qué filas y en qué orden. Las tuyas, en cada pantalla.",
    "Play the banner": "Reproducir la portada",
    "The featured title at the top of Home plays a few silent seconds.": "El título destacado de Inicio se reproduce unos segundos, sin sonido.",
    "Trailers": "Tráilers",
    "A show's or movie's page plays three minutes of it, from somewhere in the middle, behind the title.": "La página de una serie o película reproduce tres minutos, de algún punto intermedio, detrás del título.",
    "Previews": "Vistas previas", "Stopping on a title plays a few seconds of it.": "Al detenerte en un título se reproducen unos segundos.",
    "Hide spoilers": "Ocultar spoilers",
    "Pictures and descriptions of episodes you haven't watched stay blurred until you point at them.": "Las imágenes y descripciones de los episodios que no has visto quedan borrosas hasta que las señalas.",
    "This device": "Este dispositivo", "Sofa as an app": "Sofa como app", "Install": "Instalar",
    "Its name, for playing on it from your phone": "Su nombre, para reproducir en él desde tu teléfono",
    "TV mode": "Modo TV", "Big buttons for a remote": "Botones grandes para el control remoto",
    "Turns on by itself on Fire TV, Android TV and smart TVs.": "Se activa solo en Fire TV, Android TV y teles inteligentes.",
    "Done": "Listo", "Language": "Idioma", "Device": "Dispositivo",
    "English, or Spanish for the pages you use every day. The Server pages are in English.": "Inglés o español en las páginas de todos los días. Las del servidor están en inglés.",
    "Sofa on your home screen, full screen, with its own icon.": "Sofa en tu pantalla de inicio, a pantalla completa y con su propio ícono.",
    "Not now": "Ahora no", "Sofa is on your home screen now.": "Sofa ya está en tu pantalla de inicio.",
    "Put Sofa on this device's home screen or in its apps, with its own icon.": "Pon Sofa en la pantalla de inicio de este dispositivo o entre sus apps, con su propio ícono.",

    // ---- Play on (the phone as a remote)
    "Play on": "Reproducir en", "Play here, as usual": "Reproducir aquí, como siempre", "Play here again": "Reproducir aquí otra vez",
    "Remote": "Control", "Stop": "Detener", "Back 10 seconds": "Retroceder 10 segundos",
    "Forward 30 seconds": "Adelantar 30 segundos", "Forward 10 seconds": "Adelantar 10 segundos", "Next episode": "Siguiente episodio",
    "A screen shows up here while Sofa is open on it, signed in as you. Give this one a name under Theme.": "Una pantalla aparece aquí mientras tenga Sofa abierto con tu sesión. Ponle nombre a esta en Tema.",
    "Open it on your phone": "Ábrelo en tu teléfono",
    "Point your phone's camera at the code, or type the address.": "Apunta la cámara de tu teléfono al código o escribe la dirección.",

    // ---- downloads
    "Checking…": "Revisando…", "This file plays on this device as it is.": "Este archivo se reproduce en este dispositivo tal como está.",
    "The travel copy is ready: 720p MP4 with its subtitles, for any phone, tablet or laptop.": "La copia de viaje está lista: MP4 a 720p con sus subtítulos, para cualquier teléfono, tableta o laptop.",
    "You can close this; Sofa carries on. Come back here to download it.": "Puedes cerrar esto; Sofa sigue trabajando. Vuelve aquí para descargarla.",
    "Make a travel copy": "Hacer una copia de viaje", "Or": "O", "download the original": "descarga el original",

    // ---- the player
    "Video player": "Reproductor de video", "Back to library": "Volver a la biblioteca", "Back to browse": "Volver a explorar",
    "Pause": "Pausa", "Mute": "Silenciar", "Volume": "Volumen", "Seek": "Avanzar o retroceder", "Full screen": "Pantalla completa",
    "Picture in picture": "Imagen en imagen", "Picture in picture (P)": "Imagen en imagen (P)", "Episodes (E)": "Episodios (E)",
    "Audio and subtitles": "Audio y subtítulos", "Audio and subtitles (C)": "Audio y subtítulos (C)",
    "Playback speed": "Velocidad", "Player options": "Opciones del reproductor", "Options": "Opciones",
    "Keyboard shortcuts": "Atajos de teclado", "Keyboard shortcuts (?)": "Atajos de teclado (?)",
    "Watch together (W)": "Ver juntos (W)", "Record": "Grabar", "Record what's on (R)": "Grabar lo que están dando (R)",
    "Play on an Apple TV or AirPlay speaker": "Reproducir en un Apple TV o bocina AirPlay",
    "Glow around the picture": "Resplandor alrededor de la imagen", "Up next": "A continuación", "Previous": "Anterior",
    "Repeat": "Repetir", "Shuffle": "Aleatorio", "Like": "Me gusta", "Music player": "Reproductor de música",
    "Are you still watching?": "¿Sigues viendo?", "Hide": "Ocultar", "Play now": "Reproducir ya",
    "Watch credits": "Ver los créditos", "Loading…": "Cargando…", "Getting the video ready…": "Preparando el video…",
    "Getting the next part ready…": "Preparando la siguiente parte…",
    "Waiting for a few seconds of video, so it doesn't keep stopping.": "Esperando unos segundos de video para que no se detenga a cada rato.",
    "Making the picture a little smaller…": "Haciendo la imagen un poco más pequeña…",
    "This computer can't convert this video quite fast enough, so it kept stopping.": "Esta computadora no convierte este video lo bastante rápido, por eso se detenía.",
    "Smaller picture, so it stops stopping (Options → Picture)": "Imagen más pequeña para que no se detenga (Opciones → Imagen)",
    "Switching sound track…": "Cambiando la pista de audio…", "Changing the picture…": "Cambiando la imagen…",
    "Putting the subtitles on the picture…": "Poniendo los subtítulos en la imagen…",
    "Taking the subtitles off…": "Quitando los subtítulos…",
    "This video can't be played": "Este video no se puede reproducir",
    "This video can't be played here": "Este video no se puede reproducir aquí",
    "This video can't be played right now": "Este video no se puede reproducir ahora",
    "This video stopped": "El video se detuvo", "Try again": "Intentar de nuevo",
    "Convert this file to MP4": "Convertir este archivo a MP4", "Repackaged": "Reempaquetado", "Converted": "Convertido",
    "Audio": "Audio", "Subtitles": "Subtítulos", "on the picture": "en la imagen",
    "Drawn onto the picture (Blu-ray and DVD subtitles are pictures). Sofa converts the video to do it.": "Se dibujan sobre la imagen (los subtítulos de Blu-ray y DVD son imágenes). Sofa convierte el video para hacerlo.",
    "This video has no subtitles. Put a .srt file with the same name next to it.": "Este video no tiene subtítulos. Pon junto a él un archivo .srt con el mismo nombre.",
    "Skip Intro": "Saltar intro", "Skip Recap": "Saltar resumen", "Skip Credits": "Saltar créditos",
    "Intro": "Intro", "Recap": "Resumen", "Credits": "Créditos", "Skipped the intro": "Intro saltada",
    "Skipped the recap": "Resumen saltado",
    "Good night. The sleep timer stopped playing; press Play to carry on.": "Buenas noches. El temporizador detuvo el video; presiona Reproducir para seguir.",
    "Playing": "Reproduciendo", "The original file, as it is": "El archivo original, tal como está",
    "Play the next episode": "Reproducir el siguiente episodio",
    "Starts the next one when this ends, or when the credits start.": "Empieza el siguiente cuando este termina o cuando empiezan los créditos.",
    "Skip intros by themselves": "Saltar las intros automáticamente",
    "Otherwise a Skip Intro button appears.": "Si no, aparece un botón Saltar intro.",
    "Ask \"Are you still watching?\"": "Preguntar «¿Sigues viendo?»",
    "After three episodes in a row with no buttons pressed.": "Después de tres episodios seguidos sin tocar ningún botón.",
    "Night mode": "Modo nocturno",
    "Loud scenes quieter, voices clearer. For late nights and thin TV speakers.": "Baja las escenas ruidosas y aclara las voces. Para la noche y para bocinas de tele pequeñas.",
    "Picture": "Imagen",
    "For video converted as it plays. Lower is lighter for an older computer or weak Wi-Fi.": "Para el video que se convierte mientras se reproduce. Más bajo exige menos a una computadora vieja o a un Wi-Fi débil.",
    "Auto": "Automática", "Sleep timer": "Temporizador", "Off.": "Apagado.", "End of this": "Al final",
    "1 hour": "1 h", "Stops at the end of this episode.": "Se detiene al terminar este episodio.",
    "Stops at the end of this video.": "Se detiene al terminar este video.", "Speed": "Velocidad",
    "Subtitle style": "Estilo de los subtítulos", "On a dark box": "Sobre fondo oscuro", "Outlined": "Con contorno",
    "Subtitle timing": "Sincronía de los subtítulos",
    "As the file has them. Out of sync? Move them.": "Como vienen en el archivo. ¿Desfasados? Muévelos.",
    "In sync": "En sincronía", "Subtitles earlier": "Subtítulos antes", "Subtitles later": "Subtítulos después",
    "Intro and credits": "Intro y créditos", "Mark the intro by hand": "Marcar la intro a mano",
    "Ends here: this episode": "Termina aquí: este episodio", "Ends here: whole season": "Termina aquí: toda la temporada",
    "Got it. Sofa won't offer that skip on this episode.": "Entendido. Sofa ya no ofrecerá ese salto en este episodio.",
    "Play / pause": "Reproducir / pausa", "Skip intro / recap": "Saltar intro / resumen", "Slower / faster": "Más lento / más rápido",
    "Jump to 0% to 90%": "Ir del 0% al 90%", "This list": "Esta lista", "Space or K": "Espacio o K", "0 to 9": "0 a 9",
    "On a phone: double-tap the left or right side to skip 10 seconds.": "En un teléfono: toca dos veces el lado izquierdo o derecho para saltar 10 segundos.",
    "You're watching": "Estás viendo", "LIVE": "EN VIVO", "Tuning in…": "Sintonizando…",
    "This channel isn't available right now": "Este canal no está disponible ahora",
    "Free channels come and go. Try another one, or try this one later.": "Los canales gratis van y vienen. Prueba otro, o este más tarde.",

    // ---- the browser's own question boxes and short answers
    "Show no details": "No mostrar detalles", "Premiered": "Estreno", "Not shared any more.": "Ya no se comparte.",
    "Shared. Switch the public library on in Server → Sharing to send the link.": "Compartido. Activa la biblioteca pública en Servidor → Compartir para enviar el enlace.",
    // ---- languages and a title's file (cards, pages, the filter)
    "from the file's name": "por el nombre del archivo", "from the track's name": "por el nombre de la pista",
    "From the file's name: its tracks don't say": "Por el nombre del archivo: sus pistas no lo dicen",
    "The track has no language tag: this is from the track's own name": "La pista no tiene etiqueta de idioma: esto sale de su propio nombre",
    "The file doesn't say, and neither does its name": "No lo dice el archivo ni su nombre",
    "Any audio": "Cualquier audio", "Two or more": "Dos o más", "Audio language": "Idioma del audio",
    "Two or more languages": "Dos o más idiomas", "This file": "Este archivo", "Details": "Detalles",
    "Reading the file…": "Leyendo el archivo…", "Sofa hasn't read this file yet.": "Sofa aún no ha leído este archivo.",
    "Sofa couldn't read this file's details just now.": "Sofa no pudo leer los detalles de este archivo por ahora.",
    "Language not labelled": "Idioma sin etiqueta", "Plays as it is on this device": "Se reproduce tal como está en este dispositivo",
    "Repackaged for this device": "Reempaquetado para este dispositivo", "Converted for this device": "Convertido para este dispositivo",
    "Can't play here yet": "Aún no se puede reproducir aquí",
    "the picture and sound are sent as they are": "la imagen y el audio se envían tal como están",
    "Made in": "Idioma original", "File": "Archivo", "No sound": "Sin audio",
    "the title's original language, from its details: this file may be dubbed": "el idioma original del título, según sus detalles: este archivo puede estar doblado",
    "plays first": "se reproduce primero", "commentary": "comentarios", "audio description": "audiodescripción",
    "forced": "forzados", "interlaced": "entrelazado", "a file beside the video": "un archivo junto al video",
    "Skip Intro found": "Intro encontrada", "scrubbing previews made": "miniaturas de avance listas",
    "Copied.": "Copiado.", "Copy this:": "Copia esto:", "Installing…": "Instalando…", "Starting…": "Empezando…"
  };

  // Patterns: "{}" anything, "{n}" a number. First match wins; longer ones first where two could match.
  const PATTERNS = [
    ["Sofa {} · Project by", "Sofa {1} · Un proyecto de"],
    ["Library updated {}. New files in the Inbox show up on their own.", "Biblioteca actualizada: {1}. Los archivos nuevos del Inbox aparecen solos."],
    ["Library updated {}.", "Biblioteca actualizada: {1}."],
    ["{n} results for \"{}\"", "{1} resultados para «{2}»"], ["1 result for \"{}\"", "1 resultado para «{1}»"],
    ["Nothing matches \"{}\" yet.", "Aún no hay coincidencias para «{1}»."],
    ["See all results for \"{}\"", "Ver todos los resultados para «{1}»"],
    ["With \"{}\" in the name", "Con «{1}» en el nombre"],
    ["New episode {}", "Episodio nuevo {1}"], ["{} · next for you: {}", "{1} · el siguiente para ti: {2}"],
    ["{n} new episodes", "{1} episodios nuevos"], ["{n} new", "{1} nuevos"],
    ["{} left", "quedan {1}"], ["Resumed at {}", "Continúa desde {1}"], ["ends {}", "termina a las {1}"],
    ["Next episode in {n}s", "Siguiente episodio en {1} s"], ["S{n} E{n}, Episode {n}", "S{1} E{2}, Episodio {3}"], ["Episode {n}", "Episodio {1}"], ["Season {n}", "Temporada {1}"],
    ["Special E{n}", "Especial E{1}"], ["{n} min", "{1} min"], ["{n} h {n} min", "{1} h {2} min"],
    ["{n} min ago", "hace {1} min"], ["{n} h ago", "hace {1} h"], ["Aired {}", "Emitido el {1}"],
    ["aired {}", "emitido el {1}"], ["airs {}", "se emite {1}"], ["{n} watched", "{1} vistos"],
    ["{} to now", "{1} a la fecha"], ["{n} to {n}", "{1} a {2}"],
    ["and {n} more", "y {1} más"], ["Play {}", "Reproducir {1}"], ["Download {}", "Descargar {1}"],
    ["Download ({})", "Descargar ({1})"], ["({}) for a player like VLC.", "({1}) para un reproductor como VLC."],
    ["That didn't work: {}", "No funcionó: {1}"],
    ["This {} file won't play on this device by itself. Sofa can make a travel copy: 720p MP4 with its subtitles, about {}.",
     "Este archivo {1} no se reproduce por sí solo en este dispositivo. Sofa puede hacer una copia de viaje: MP4 a 720p con sus subtítulos, de unos {2}."],
    ["This {} file won't play on this device by itself. Sofa can make a travel copy: 720p MP4 with its subtitles.",
     "Este archivo {1} no se reproduce por sí solo en este dispositivo. Sofa puede hacer una copia de viaje: MP4 a 720p con sus subtítulos."],
    ["Sign in to {}.", "Inicia sesión en {1}."], ["Signed in as {}.", "Sesión iniciada como {1}."], ["Hi, {}.", "Hola, {1}."],
    ["For {}. Whoever runs it lets you in, then you sign in with this name and password.", "Para {1}. Quien lo administra te da acceso; después inicias sesión con este nombre y esta contraseña."],
    ["At least {n} characters.", "Al menos {1} caracteres."],
    ["Once whoever runs {} lets you in, sign in as", "Cuando quien administra {1} te dé acceso, inicia sesión como"],
    ["On your phone, open Sofa (", "En tu teléfono, abre Sofa ("], ["), signed in, and scan this, or go to", "), con tu sesión iniciada, y escanea esto, o ve a"],
    ["Code {}", "Código {1}"], ["How {} looks in \"Who's watching?\".", "Cómo se ve {1} en «¿Quién ve?»."],
    ["Color {n}", "Color {1}"], ["This {}", "Este dispositivo ({1})"], ["Playing from {}", "Reproduciendo desde {1}"],
    ["Now Play sends things to {}.", "Ahora Reproducir envía las cosas a {1}."],
    ["What {} sees on Home, top to bottom, on every screen. Rows with nothing in them don't show.", "Lo que {1} ve en Inicio, de arriba abajo, en cada pantalla. Las filas vacías no se muestran."],
    ["Move {} up", "Subir {1}"], ["Move {} down", "Bajar {1}"], ["Show {}", "Mostrar {1}"],
    ["Someone asked for an account", "Alguien pidió una cuenta"], ["{n} people asked for an account", "{1} personas pidieron una cuenta"],
    ["{} hasn't shared any shows or movies yet. Come back later.", "{1} aún no ha compartido series ni películas. Vuelve más tarde."],
    ["Stopping on a title plays a few seconds of it. Off by itself on this box, where they slow everything else down.", "Al detenerte en un título se reproducen unos segundos. En esta caja vienen apagadas, porque hacen más lento todo lo demás."],
    ["Adapting {} for this device", "Adaptando {1} para este dispositivo"], ["Adapted for this device: {}", "Adaptado para este dispositivo: {1}"],
    ["The server said: {}", "El servidor dijo: {1}"],
    ["Repackaged live for this device ({}) · {}", "Reempaquetado al momento para este dispositivo ({1}) · {2}"],
    ["Repackaged live for this device ({})", "Reempaquetado al momento para este dispositivo ({1})"],
    ["Repackaged live for this device · {}", "Reempaquetado al momento para este dispositivo · {1}"],
    ["Repackaged live for this device", "Reempaquetado al momento para este dispositivo"],
    ["Converted live for this device ({}) · {}", "Convertido al momento para este dispositivo ({1}) · {2}"],
    ["Converted live for this device ({})", "Convertido al momento para este dispositivo ({1})"],
    ["Converted live for this device · {}", "Convertido al momento para este dispositivo · {1}"],
    ["Converted live for this device", "Convertido al momento para este dispositivo"],
    ["The original file, as it is · {}", "El archivo original, tal como está · {1}"],
    ["Auto ({n}p now)", "Automática ({1}p ahora)"], ["Stops at {}.", "Se detiene a las {1}."],
    ["Shown {} s later than the file says.", "Se muestran {1} s después de lo que dice el archivo."],
    ["Shown {} s earlier than the file says.", "Se muestran {1} s antes de lo que dice el archivo."],
    ["Starts here ({})", "Empieza aquí ({1})"], ["Wrong {}", "{1} mal marcado"], ["Intro starts at {}", "La intro empieza en {1}"],
    ["Saved: intro {}", "Guardado: intro {1}"],
    ["Pause where the intro starts, press \"Starts here\"; then where it ends, press one of the \"Ends here\" buttons. Start: {}.", "Pon pausa donde empieza la intro y presiona «Empieza aquí»; luego, donde termina, presiona uno de los botones «Termina aquí». Inicio: {1}."],
    ["Pause where the intro starts, press \"Starts here\"; then where it ends, press one of the \"Ends here\" buttons.", "Pon pausa donde empieza la intro y presiona «Empieza aquí»; luego, donde termina, presiona uno de los botones «Termina aquí»."],
    ["{}  (Page Up / Page Down changes channel)", "{1}  (Re Pág / Av Pág cambia de canal)"],
    ["{} · no details found yet", "{1} · aún sin detalles"], ["{} · details from {}", "{1} · detalles de {2}"],
    ["{n} of {n} episodes", "{1} de {2} episodios"], ["{n} tracks, not labelled", "{1} pistas, sin etiqueta"],
    ["Subtitles: {}", "Subtítulos: {1}"], ["This file's details: {}", "Detalles de este archivo: {1}"],
    ["{} overall", "{1} en total"], ["added {}", "agregado el {1}"], ["pictures ({})", "imágenes ({1})"],
    ["The file's name says {}. Its tracks aren't labelled, so Sofa can't say which is which.", "El nombre del archivo dice {1}. Sus pistas no tienen etiqueta, así que Sofa no puede decir cuál es cuál."],
    ["Something went wrong ({})", "Algo salió mal ({1})"]
  ];

  // "3 seasons", "1 episode": the app counts things in one way (plural() in app.js).
  const NOUNS = { season: ["temporada", "temporadas"], episode: ["episodio", "episodios"], movie: ["película", "películas"],
                  show: ["serie", "series"], title: ["título", "títulos"], result: ["resultado", "resultados"],
                  video: ["video", "videos"], song: ["canción", "canciones"] };
  // Genres come from the lookup services, in English; a title's own name never comes through here.
  const GENRES = { "Action": "Acción", "Adventure": "Aventura", "Animation": "Animación", "Anime": "Anime", "Children": "Infantil",
                   "Comedy": "Comedia", "Crime": "Crimen", "Documentary": "Documental", "Drama": "Drama", "Family": "Familiar",
                   "Fantasy": "Fantasía", "Food": "Cocina", "History": "Historia", "Horror": "Terror", "Kids": "Infantil",
                   "Medical": "Médico", "Music": "Música", "Mystery": "Misterio", "Nature": "Naturaleza", "Reality": "Reality",
                   "Romance": "Romance", "Science Fiction": "Ciencia ficción", "Science-Fiction": "Ciencia ficción",
                   "Sports": "Deportes", "Supernatural": "Sobrenatural", "Thriller": "Suspenso", "Travel": "Viajes", "War": "Guerra",
                   "Western": "Western", "Legal": "Legal", "Espionage": "Espionaje", "Adult": "Adultos", "Talk Show": "Programa de entrevistas",
                   "Game Show": "Concursos", "News": "Noticias", "TV Movie": "Película para TV", "Musical": "Musical" };
  // A sound track's line in the player's menu: its language is named, the rest is the file's.
  const LANGS = { "English": "Inglés", "Spanish": "Español", "French": "Francés", "German": "Alemán", "Italian": "Italiano",
                  "Portuguese": "Portugués", "Japanese": "Japonés", "Korean": "Coreano", "Chinese": "Chino", "Russian": "Ruso",
                  "Dutch": "Neerlandés", "Arabic": "Árabe", "Hindi": "Hindi", "Stereo": "Estéreo", "Mono": "Mono" };

  const SAFE = /^(Episode \d+|Season \d+|Specials|Extra|Untitled)$/;       // (words the app itself puts where a title goes)
  // Why a video is adapted, as the server words it: "AC3 sound", "HEVC 10-bit video", "MKV file".
  const WHY = /^((?:[\w.:+-]+ ){1,3})(sound|video|file)$/;
  const why = s => {
    const parts = s.split(", ");
    if (!parts.every(p => WHY.test(p))) return s;
    return parts.map(p => { const m = WHY.exec(p); return ({ sound: "audio ", video: "video ", file: "archivo " })[m[2]] + m[1].trim(); }).join(", ");
  };
  const compiled = PATTERNS.map(([en, es]) => {
    const rx = en.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{n\}/g, "(\\d+)").replace(/\{\}/g, "(.+?)");
    return [new RegExp("^" + rx + "$"), es, en.slice(0, en.indexOf("{") < 0 ? en.length : en.indexOf("{"))];
  });
  const count = /^(\d+) ([a-z]+?)s?$/;
  const cache = new Map();

  function whole(s) {
    if (Object.prototype.hasOwnProperty.call(WORDS, s)) return WORDS[s];
    const c = count.exec(s);
    if (c && NOUNS[c[2]]) return c[1] + " " + NOUNS[c[2]][c[1] === "1" ? 0 : 1];
    for (let i = 0; i < compiled.length; i++) {
      const p = compiled[i];
      if (p[2] && s.indexOf(p[2]) !== 0) continue;          // (cheap: most patterns start with fixed words)
      const m = p[0].exec(s);
      if (m) return p[1].replace(/\{(\d)\}/g, (_, n) => SAFE.test(m[+n]) ? whole(m[+n]) : why(m[+n]))
        .replace(/([^.])\.\.(?!\.)/g, "$1.");               // ("19 nov, 6:02 a.m." ends in its own full stop)
    }
    return null;
  }
  /* A string as the page drew it -> Spanish, or null to leave it. `loose`: a list where some parts are the file's own
     words ("English · Dolby Digital 5.1"): the parts Sofa knows are put in Spanish, the rest stay. */
  function say(s, loose) {
    if (s.length < 2 || s.length > 400 || !/[A-Za-z]{2}/.test(s)) return null;
    const key = (loose ? "~" : "") + s;
    if (cache.has(key)) return cache.get(key);
    let out = whole(s);
    if (out == null) {
      for (const sep of [" · ", ", "]) {
        if (s.indexOf(sep) < 0) continue;
        const parts = s.split(sep);
        const done = parts.map(p => whole(p) || (loose ? LANGS[p] : GENRES[p]) || (/[A-Za-z]/.test(p) && !loose ? null : p));     // ("S1 E2, Watched": an episode's own title stays)
        if (done.every(p => p != null) && done.some((p, i) => p !== parts[i])) { out = done.join(sep); break; }
      }
    }
    if (out == null && loose && why(s) !== s) out = why(s);        // ("AC3 sound", alone under "Repackaged for this device")
    if (cache.size > 3000) cache.clear();
    cache.set(key, out);
    return out;
  }

  // What's the library's own (a title, a description, a person's name, a file's name) is never touched.
  const DATA = ".t1, .hero h1, .hero-logo, .episode h3, .pe-head h3, .pe-text b, .pe-sum, .pop-title, .pop-sub, .placeholder, .sg-text b, .sg-text small, .who .name, .fd-name, .summary, .tagline, .ep-sum, .p-show, .pname, .more-me b, .who-name, " +
               ".next-card .name, .suggest .s-name, .rights, .po-info span:not(:first-of-type) i, [data-notr]";
  const GENRE_PLACES = ".genre-chips, .chips, .facts, .page-head h1, .rail-title, .rail h2, .collection-title, .eyebrow, .tag-cloud";
  const LOOSE = ".cc-menu, .file-details";
  const ATTRS = ["placeholder", "aria-label", "title", "data-part"];
  let writing = false;

  function text(node) {
    const p = node.parentElement;
    if (!p || p.closest("script, style, svg, textarea, [contenteditable]")) return;
    const raw = node.nodeValue, s = raw.replace(/\s+/g, " ").trim();
    if (!s) return;
    let out = null;
    if (p.closest(DATA)) out = SAFE.test(s) ? whole(s) : null;
    else {
      out = say(s, !!p.closest(LOOSE));
      if (out == null && GENRES[s] && p.closest(GENRE_PLACES)) out = GENRES[s];
    }
    if (out != null && out !== s) node.nodeValue = raw.replace(/^(\s*)[\s\S]*?(\s*)$/, (_, a, b) => a + out + b);
  }
  function attrs(el) {
    if (el.closest && el.closest("svg")) return;
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (!v || (a !== "data-part" && el.closest(".card, .frame, .hero-logo, .pname") && !/^(Play|Download|Remove|Add|Favorite|More info|Mark)/.test(v))) continue;
      const out = say(v.trim(), false);
      if (out != null && out !== v) el.setAttribute(a, out);
    }
  }
  function sweep(root) {
    if (root.nodeType === 3) return text(root);
    if (root.nodeType !== 1 || /^(SCRIPT|STYLE|svg)$/i.test(root.tagName)) return;
    attrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) { if (n.nodeType === 3) text(n); else attrs(n); }
  }
  const watch = new MutationObserver(list => {
    if (writing) return;
    writing = true;
    try {
      for (const m of list) {
        if (m.type === "characterData") text(m.target);
        else if (m.type === "attributes") attrs(m.target);
        else m.addedNodes.forEach(sweep);
      }
    } finally { watch.takeRecords(); writing = false; }       // (its own writes aren't read again)
  });
  // From the first element on: what index.html holds and what app.js draws are both seen as they arrive, before
  // the screen is painted, so no English shows first.
  watch.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  function start() {
    writing = true;
    try { sweep(document.body); } finally { watch.takeRecords(); writing = false; }
  }

  // The browser's own boxes (they aren't part of the page).
  for (const name of ["confirm", "alert", "prompt"]) {
    const own = window[name];
    window[name] = function (msg) { const a = [].slice.call(arguments); a[0] = say(String(msg), false) || msg; return own.apply(window, a); };
  }
  // Dates and times: Spanish where the app leaves the choice to the device (this device may be set to English).
  const region = (/-([A-Za-z]{2})\b/.exec(navigator.language || "") || [])[1];
  const LOCALE = /^es\b/i.test(navigator.language || "") ? navigator.language : "es-" + (region || "US").toUpperCase();
  for (const name of ["toLocaleDateString", "toLocaleTimeString", "toLocaleString"]) {
    const own = Date.prototype[name];
    Date.prototype[name] = function (locales, options) {
      return own.call(this, locales === undefined || (Array.isArray(locales) && !locales.length) ? LOCALE : locales, options);
    };
  }

  document.documentElement.lang = "es";
  window.SofaSpanish = { say, words: WORDS, patterns: PATTERNS, nouns: NOUNS, genres: GENRES };
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
})();
