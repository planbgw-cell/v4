// Lucide 아이콘 초기화
        lucide.createIcons();

        // 3D 플립북 조작용 변수 및 데이터
        let currentPage = 1;
        const totalPage = 3;
        const pageIndicator = document.getElementById('page-indicator');
        
        function updatePageIndicator() {
            if (currentPage === 1) {
                pageIndicator.textContent = "COVER / PAGE 1";
            } else if (currentPage === 2) {
                pageIndicator.textContent = "PAGE 2 / PAGE 3";
            } else if (currentPage === 3) {
                pageIndicator.textContent = "PAGE 4 / END COVER";
            }
        }

        function nextPage() {
            if (currentPage < totalPage) {
                const pageEl = document.getElementById(`p${currentPage}`);
                if (pageEl) {
                    pageEl.classList.add('flipped');
                    // 3D depth 조절
                    pageEl.style.zIndex = 10 + currentPage;
                }
                currentPage++;
                updatePageIndicator();
                playPageTurnSound();
            }
        }

        function prevPage() {
            if (currentPage > 1) {
                currentPage--;
                const pageEl = document.getElementById(`p${currentPage}`);
                if (pageEl) {
                    pageEl.classList.remove('flipped');
                    // 3D depth 원래대로 복구
                    pageEl.style.zIndex = 50 - currentPage;
                }
                updatePageIndicator();
                playPageTurnSound();
            }
        }

        // 3D 입체북 가상 오디오 재생 및 연동 장치
        const audioData = {
            wedding: {
                badge: 'ROMANTIC WEDDING',
                title: '축복 가득한 날, 우리들의 빛나는 웨딩 앨범',
                track: 'Clair de Lune (달빛 - 클래식 오케스트라)',
                bgImage: 'https://images.unsplash.com/photo-1519741497674-611481863552?auto=format&fit=crop&q=80&w=1200',
                color: '#6d57ff'
            },
            travel: {
                badge: 'WANDERLUST ADVENTURE',
                title: '끝없는 지평선 너머로 마주한 찬란한 노을',
                track: 'Acoustic Sunset Breeze (인디 어쿠스틱 세션)',
                bgImage: 'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&q=80&w=1200',
                color: '#a855f7'
            },
            baby: {
                badge: 'INNOCENT CUDDLE',
                title: '눈을 뗄 수 없는 천사 같은 아이의 미소 일기',
                track: 'Toy Box Music Lullaby (소리가 움직이는 오르골)',
                bgImage: 'https://images.unsplash.com/photo-1519689680058-324335c77eba?auto=format&fit=crop&q=80&w=1200',
                color: '#f43f5e'
            }
        };

        let currentActiveTheme = 'wedding';
        let isAudioPlaying = false;
        let audioCtx = null;
        let oscillator = null;
        let visualizerInterval = null;

        function switchTheme(themeKey) {
            currentActiveTheme = themeKey;
            
            // 버튼 활성화 클래스 변경
            const buttons = ['wedding', 'travel', 'baby'];
            buttons.forEach(k => {
                const btn = document.getElementById(`btn-theme-${k}`);
                if (k === themeKey) {
                    btn.className = "px-5 py-2 rounded-full text-xs font-bold transition-all duration-300 bg-flairy-primary text-white";
                } else {
                    btn.className = "px-5 py-2 rounded-full text-xs font-bold transition-all duration-300 text-flairy-muted hover:text-white";
                }
            });

            // 데이터 반영
            const data = audioData[themeKey];
            document.getElementById('theme-badge').textContent = data.badge;
            document.getElementById('theme-display-title').textContent = data.title;
            document.getElementById('theme-track-title').textContent = data.track;
            document.getElementById('theme-banner-img').src = data.bgImage;

            // 오디오 중단 상태일 경우 플레이버튼 아이콘 초기화
            if (isAudioPlaying) {
                stopWebAudio();
                startWebAudio(themeKey);
            }
        }

        // Web Audio API를 활용한 실제 고품격 감성 앰비언트음 합성 연출 (음악 파일 미필요)
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

            // 가상 오디오 스펙트럼 작동 효과 연출
            const visualizer = document.getElementById('audio-visualizer');
            visualizer.classList.remove('opacity-30');
            const bars = visualizer.children;
            visualizerInterval = setInterval(() => {
                for (let bar of bars) {
                    bar.style.height = `${Math.floor(Math.random() * 12) + 3}px`;
                }
            }, 150);

            // Web Audio 가동
            try {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                audioCtx = new AudioContext();
                
                // 테마에 따른 음계 신디사이징
                let frequencies = [261.63, 329.63, 392.00, 523.25]; // C major 기본
                if (themeType === 'travel') frequencies = [293.66, 369.99, 440.00, 587.33]; // D major 활기참
                if (themeType === 'baby') frequencies = [349.23, 440.00, 523.25, 698.46]; // F major 포근함

                oscillator = audioCtx.createOscillator();
                const gainNode = audioCtx.createGain();
                
                oscillator.type = 'triangle'; // 부드러운 하프 소리 느낌
                oscillator.frequency.setValueAtTime(frequencies[0], audioCtx.currentTime);
                
                // 아르페지오 루프 효과 부여
                let index = 0;
                setInterval(() => {
                    if (oscillator && audioCtx && isAudioPlaying) {
                        index = (index + 1) % frequencies.length;
                        oscillator.frequency.setValueAtTime(frequencies[index], audioCtx.currentTime);
                    }
                }, 800);

                gainNode.gain.setValueAtTime(0.08, audioCtx.currentTime); // 매우 자극적이지 않고 은은하게
                oscillator.connect(gainNode);
                gainNode.connect(audioCtx.destination);
                oscillator.start();
            } catch (e) {
                console.log("Audio Context is not supported in this browser.");
            }
        }

        function stopWebAudio() {
            isAudioPlaying = false;
            document.getElementById('audio-play-icon').setAttribute('data-lucide', 'play');
            lucide.createIcons();

            // 비주얼라이저 스톱
            if (visualizerInterval) clearInterval(visualizerInterval);
            const visualizer = document.getElementById('audio-visualizer');
            visualizer.classList.add('opacity-30');
            for (let bar of visualizer.children) {
                bar.style.height = '4px';
            }

            // 오디오 제거
            if (oscillator) {
                try {
                    oscillator.stop();
                } catch (e) {}
                oscillator = null;
            }
            if (audioCtx) {
                audioCtx.close();
                audioCtx = null;
            }
        }

        // 책 넘길 때 종이 스치는 가상 백색 사운드 (물리 피드백 향상)
        function playPageTurnSound() {
            try {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                const turnCtx = new AudioContext();
                const bufferSize = turnCtx.sampleRate * 0.15; // 0.15초 소리
                const buffer = turnCtx.createBuffer(1, bufferSize, turnCtx.sampleRate);
                const data = buffer.getChannelData(0);
                
                // 화이트 노이즈 생성
                for (let i = 0; i < bufferSize; i++) {
                    data[i] = Math.random() * 2 - 1;
                }
                
                const noiseNode = turnCtx.createBufferSource();
                noiseNode.buffer = buffer;
                
                // 저음 필터를 통해 바람/종이 쓸리는 느낌 연출
                const filter = turnCtx.createBiquadFilter();
                filter.type = 'lowpass';
                filter.frequency.setValueAtTime(800, turnCtx.currentTime);
                filter.Q.setValueAtTime(1, turnCtx.currentTime);
                
                const gain = turnCtx.createGain();
                gain.gain.setValueAtTime(0.04, turnCtx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, turnCtx.currentTime + 0.14);
                
                noiseNode.connect(filter);
                filter.connect(gain);
                gain.connect(turnCtx.destination);
                
                noiseNode.start();
            } catch (e) {}
        }

        // Before/After 이미지 분할 드래그 메커니즘
        const sliderContainer = document.getElementById('slider-container');
        const dragBar = document.getElementById('drag-bar');
        const afterImage = document.getElementById('after-image');

        let isDragging = false;

        function moveSlider(clientX) {
            const rect = sliderContainer.getBoundingClientRect();
            let x = clientX - rect.left;
            
            // 바운더리 체크
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

        // 모바일 터치 대응
        dragBar.addEventListener('touchstart', () => isDragging = true);
        window.addEventListener('touchend', () => isDragging = false);
        window.addEventListener('touchmove', (e) => {
            if (!isDragging) return;
            moveSlider(e.touches[0].clientX);
        });

        // 가상 업로드 & 실시간 3D 앨범 투영 시뮬레이션
        const simUploadZone = document.getElementById('sim-upload-zone');
        const simImageInput = document.getElementById('sim-image-input');
        const simPhotoHolder = document.getElementById('sim-photo-holder');
        const simUploadPrompt = document.getElementById('sim-upload-prompt');

        // 트리거 설정
        simUploadZone.addEventListener('click', () => simImageInput.click());

        // 드래그앤드롭 이벤트 바인딩 (이탈 오류 방지 및 실시간 인터랙션 극대화)
        ['dragenter', 'dragover'].forEach(eventName => {
            simUploadZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                simUploadZone.classList.add('border-flairy-secondary', 'bg-white/[0.06]');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            simUploadZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                simUploadZone.classList.remove('border-flairy-secondary', 'bg-white/[0.06]');
            }, false);
        });

        simUploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length) {
                simImageInput.files = files;
                // change 이벤트 수동 발생
                const event = new Event('change');
                simImageInput.dispatchEvent(event);
            }
        });

        // 가상 업로드 시 실제 3D 앨범 적용 프로세스
        simImageInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(event) {
                    const imgUrl = event.target.result;
                    
                    if (simPhotoHolder) {
                        // 가상 이미지 적용 및 에러 방지
                        simPhotoHolder.style.backgroundImage = `url('${imgUrl}')`;
                        simUploadPrompt.innerHTML = `
                            <div class="bg-[#05030e]/90 backdrop-blur-md px-3 py-2 rounded-lg border border-emerald-500/30">
                                <p class="text-[10px] text-emerald-400 font-bold flex items-center justify-center space-x-1">
                                    <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
                                    <span>3D 앨범 가상 적용 성공!</span>
                                </p>
                            </div>
                        `;
                        lucide.createIcons();

                        // 플립북을 업로드된 이미지가 담긴 마지막 페이지(p3)로 스무스하게 플립 유도
                        setTimeout(() => {
                            if (currentPage < totalPage) {
                                nextPage();
                                setTimeout(() => {
                                    if (currentPage < totalPage) nextPage();
                                }, 500);
                            }
                        }, 400);
                    }
                };
                reader.readAsDataURL(file);
            }
        });

        // 필터 변경 시뮬레이터 연동
        function setSimFilter(filterType) {
            const filters = ['vintage', 'noir', 'sunset'];
            filters.forEach(f => {
                const btn = document.getElementById(`btn-filter-${f}`);
                btn.className = "py-2 text-[11px] font-bold rounded-lg bg-white/5 border border-white/10 text-white transition-all";
            });

            const activeBtn = document.getElementById(`btn-filter-${filterType}`);
            activeBtn.className = "py-2 text-[11px] font-bold rounded-lg bg-flairy-primary border border-flairy-primary/30 text-white transition-all";

            // 가상 이미지 보정본 필터 조절
            const afterImg = document.getElementById('after-image');
            if (filterType === 'vintage') {
                afterImg.style.filter = "sepia(0.6) contrast(1.1) brightness(0.9) saturate(1.1)";
            } else if (filterType === 'noir') {
                afterImg.style.filter = "grayscale(1) contrast(1.3) brightness(0.9)";
            } else if (filterType === 'sunset') {
                afterImg.style.filter = "sepia(0.25) contrast(1.05) brightness(1.05) hue-rotate(-15deg) saturate(1.2)";
            }
        }

        // flairy.kr로 이동하는 전환 연출 및 랜딩페이지 최종 트랜지션
        function navigateToApp() {
            const overlay = document.getElementById('portal-overlay');
            overlay.classList.remove('pointer-events-none');
            overlay.classList.remove('opacity-0');
            overlay.classList.add('opacity-100');

            // 실제 서비스인 flairy.kr 서비스의 메인 및 에디터 구동 위치로 이동
            setTimeout(() => {
                window.location.href = '/create';
            }, 1200);
        }
