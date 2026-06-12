lucide.createIcons();

let currentPage = 1;
const totalPage = 3;
const pageIndicator = document.getElementById('page-indicator');

function updatePageIndicator() {
    if (currentPage === 1) {
        pageIndicator.textContent = "COVER / PAGE 1";
    } else if (currentPage === 2) {
        pageIndicator.textContent = "PAGE 2 / PAGE 3";
    } else if (currentPage === 3) {
        pageIndicator.textContent = "PAGE 4 / FINISHED";
    }
}

function nextPage() {
    if (currentPage < totalPage) {
        const pageEl = document.getElementById(`p${currentPage}`);
        if (pageEl) {
            pageEl.classList.add('flipped');
            pageEl.style.zIndex = 10 + currentPage;
        }
        currentPage++;
        updatePageIndicator();
        triggerPaperSound();
    }
}

function prevPage() {
    if (currentPage > 1) {
        currentPage--;
        const pageEl = document.getElementById(`p${currentPage}`);
        if (pageEl) {
            pageEl.classList.remove('flipped');
            pageEl.style.zIndex = 50 - currentPage;
        }
        updatePageIndicator();
        triggerPaperSound();
    }
}

const sliderContainer = document.getElementById('slider-container');
const dragBar = document.getElementById('drag-bar');
const afterImage = document.getElementById('after-image');
let isDragging = false;

function moveSlider(clientX) {
    const rect = sliderContainer.getBoundingClientRect();
    let x = clientX - rect.left;
    if (x < 0) x = 0;
    if (x > rect.width) x = rect.width;
    const percentage = (x / rect.width) * 100;
    dragBar.style.left = `${percentage}%`;
    afterImage.style.width = `${percentage}%`;
}

dragBar.addEventListener('mousedown', () => isDragging = true);
window.addEventListener('mouseup', () => isDragging = false);
window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    moveSlider(e.clientX);
});

dragBar.addEventListener('touchstart', () => isDragging = true);
window.addEventListener('touchend', () => isDragging = false);
window.addEventListener('touchmove', (e) => {
    if (!isDragging) return;
    moveSlider(e.touches[0].clientX);
});

const sliderPresets = {
    landscape: {
        img: "https://images.unsplash.com/photo-1519741497674-611481863552?auto=format&fit=crop&q=80&w=1200",
        filter: "saturate(1.25) contrast(1.1) brightness(1.03) sepia(0.08)"
    },
    people: {
        img: "https://images.unsplash.com/photo-1532712938310-34cb3982ef74?auto=format&fit=crop&q=80&w=1200",
        filter: "contrast(1.05) brightness(1.02) saturate(1.15) sepia(0.1)"
    },
    classic: {
        img: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&q=80&w=1200",
        filter: "grayscale(1) contrast(1.2) brightness(0.98)"
    }
};

function swapSliderPreset(presetKey) {
    const presets = ['landscape', 'people', 'classic'];
    presets.forEach(key => {
        const btn = document.getElementById(`btn-slide-${key}`);
        if (key === presetKey) {
            btn.className = "py-2 rounded-lg bg-flairy-accent text-white text-xs font-bold transition-all shadow";
        } else {
            btn.className = "py-2 rounded-lg bg-white/5 border border-white/10 text-slate-300 hover:text-white text-xs font-bold transition-all";
        }
    });

    const current = sliderPresets[presetKey];
    document.getElementById('before-img-bg').style.backgroundImage = `url('${current.img}')`;
    afterImage.style.backgroundImage = `url('${current.img}')`;
    afterImage.style.filter = current.filter;
}

const themeLibrary = {
    wedding: {
        badge: 'ROMANTIC WEDDING',
        title: '축복 가득한 날, 우리들의 빛나는 웨딩 앨범',
        track: 'Clair de Lune (달빛 - 명품 어쿠스틱 피아노)',
        img: 'https://images.unsplash.com/photo-1519741497674-611481863552?auto=format&fit=crop&q=80&w=1200',
        freq: [261.63, 329.63, 392.00, 523.25]
    },
    travel: {
        badge: 'WANDERLUST STORY',
        title: '거친 파도 너머에서 마주한 찬란한 지평선',
        track: 'Bossa Nova Wave (노을빛 은은한 바다 어쿠스틱 세션)',
        img: 'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&q=80&w=1200',
        freq: [293.66, 369.99, 440.00, 587.33]
    },
    baby: {
        badge: 'FAMILY & MEMORY',
        title: '사랑하는 우리 아이, 반짝반짝 성장 일기',
        track: 'Music Box Lullaby (영혼을 다독이는 은빛 모차르트 오르골)',
        img: 'https://images.unsplash.com/photo-1519689680058-324335c77eba?auto=format&fit=crop&q=80&w=1200',
        freq: [349.23, 440.00, 523.25, 698.46]
    }
};

let currentActiveTheme = 'wedding';
let isAudioPlaying = false;
let audioCtx = null;
let oscillator = null;
let visualizerInterval = null;

function switchTheme(themeKey) {
    currentActiveTheme = themeKey;
    const buttons = ['wedding', 'travel', 'baby'];
    buttons.forEach(k => {
        const btn = document.getElementById(`btn-theme-${k}`);
        if (k === themeKey) {
            btn.className = "px-5 py-2.5 rounded-full text-xs font-bold transition-all duration-300 bg-[#151E3D] text-white shadow-sm";
        } else {
            btn.className = "px-5 py-2.5 rounded-full text-xs font-bold transition-all duration-300 text-slate-600 hover:text-slate-950";
        }
    });

    const data = themeLibrary[themeKey];
    document.getElementById('theme-badge').textContent = data.badge;
    document.getElementById('theme-display-title').textContent = data.title;
    document.getElementById('theme-track-title').textContent = data.track;
    document.getElementById('theme-banner-img').src = data.img;

    if (isAudioPlaying) {
        stopWebAudio();
        startWebAudio(themeKey);
    }
}

function toggleAudio() {
    if (isAudioPlaying) {
        stopWebAudio();
    } else {
        startWebAudio(currentActiveTheme);
    }
}

function startWebAudio(themeType) {
    isAudioPlaying = true;
    document.getElementById('audio-play-icon').setAttribute('data-lucide', 'pause');
    lucide.createIcons();

    const visualizer = document.getElementById('audio-visualizer');
    visualizer.classList.remove('opacity-30');
    const bars = visualizer.children;
    visualizerInterval = setInterval(() => {
        for (let bar of bars) {
            bar.style.height = `${Math.floor(Math.random() * 11) + 2}px`;
        }
    }, 150);

    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        audioCtx = new AudioContext();
        const data = themeLibrary[themeType];
        oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();

        oscillator.type = 'triangle';
        oscillator.frequency.setValueAtTime(data.freq[0], audioCtx.currentTime);

        let index = 0;
        setInterval(() => {
            if (oscillator && audioCtx && isAudioPlaying) {
                index = (index + 1) % data.freq.length;
                oscillator.frequency.setValueAtTime(data.freq[index], audioCtx.currentTime);
            }
        }, 800);

        gainNode.gain.setValueAtTime(0.04, audioCtx.currentTime);
        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        oscillator.start();
    } catch (e) {
        console.log("Audio Context initialization failed.");
    }
}

function stopWebAudio() {
    isAudioPlaying = false;
    document.getElementById('audio-play-icon').setAttribute('data-lucide', 'play');
    lucide.createIcons();

    if (visualizerInterval) clearInterval(visualizerInterval);
    const visualizer = document.getElementById('audio-visualizer');
    visualizer.classList.add('opacity-30');
    for (let bar of visualizer.children) {
        bar.style.height = '4px';
    }

    if (oscillator) {
        try { oscillator.stop(); } catch (e) {}
        oscillator = null;
    }
    if (audioCtx) {
        audioCtx.close();
        audioCtx = null;
    }
}

function triggerPaperSound() {
    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        const pCtx = new AudioContext();
        const bufSize = pCtx.sampleRate * 0.15;
        const buf = pCtx.createBuffer(1, bufSize, pCtx.sampleRate);
        const pData = buf.getChannelData(0);
        for (let i = 0; i < bufSize; i++) {
            pData[i] = Math.random() * 2 - 1;
        }
        const noise = pCtx.createBufferSource();
        noise.buffer = buf;
        const filter = pCtx.createBiquadFilter();
        filter.type = 'lowpass';
        filter.frequency.setValueAtTime(600, pCtx.currentTime);
        const gain = pCtx.createGain();
        gain.gain.setValueAtTime(0.02, pCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, pCtx.currentTime + 0.14);

        noise.connect(filter);
        filter.connect(gain);
        gain.connect(pCtx.destination);
        noise.start();
    } catch (e) {}
}

const simUploadZone = document.getElementById('sim-upload-zone');
const simImageInput = document.getElementById('sim-image-input');
const simPhotoHolder = document.getElementById('sim-photo-holder');
const simUploadPrompt = document.getElementById('sim-upload-prompt');

simUploadZone.addEventListener('click', () => simImageInput.click());

['dragenter', 'dragover'].forEach(name => {
    simUploadZone.addEventListener(name, (e) => {
        e.preventDefault();
        simUploadZone.classList.add('border-flairy-accent', 'bg-[#F5EFE6]');
    }, false);
});

['dragleave', 'drop'].forEach(name => {
    simUploadZone.addEventListener(name, (e) => {
        e.preventDefault();
        simUploadZone.classList.remove('border-flairy-accent', 'bg-[#F5EFE6]');
    }, false);
});

simUploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    const dt = e.dataTransfer;
    if (dt.files.length) {
        simImageInput.files = dt.files;
        simImageInput.dispatchEvent(new Event('change'));
    }
});

simImageInput.addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(event) {
            const imgUrl = event.target.result;
            simPhotoHolder.style.backgroundImage = `url('${imgUrl}')`;
            simUploadPrompt.innerHTML = `
                <div class="bg-white/95 backdrop-blur-md px-3 py-2 rounded-lg border border-flairy-accent">
                    <p class="text-[10px] text-flairy-accent font-bold flex items-center justify-center space-x-1">
                        <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
                        <span>성공적으로 반영되었습니다!</span>
                    </p>
                </div>
            `;
            lucide.createIcons();

            setTimeout(() => {
                if (currentPage < totalPage) {
                    nextPage();
                    setTimeout(() => { if (currentPage < totalPage) nextPage(); }, 500);
                }
            }, 400);
        };
        reader.readAsDataURL(file);
    }
});

function navigateToApp() {
    const overlay = document.getElementById('portal-overlay');
    overlay.classList.remove('pointer-events-none');
    overlay.classList.remove('opacity-0');
    overlay.classList.add('opacity-100');
    setTimeout(() => {
        window.location.href = '/create';
    }, 1200);
}
