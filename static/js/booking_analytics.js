(() => {
  const page = document.querySelector('.booking-snapshot');
  if (!page) return;

  const campus = page.querySelector('#bs-campus');
  const building = page.querySelector('#bs-building');
  const filters = page.querySelector('.bs-filters');
  const buildingOptions = JSON.parse(page.querySelector('#bs-building-data').textContent) || [];
  campus.addEventListener('change', () => {
    const selected = building.value;
    const names = [...new Set(buildingOptions.filter(([location]) => !campus.value || location === campus.value)
      .map(([, name]) => name))].sort((a, b) => a.localeCompare(b));
    building.replaceChildren(new Option('All buildings', ''), ...names.map(name => new Option(name, name)));
    if (names.includes(selected)) building.value = selected;
  });
  const buildingCampusFilter = page.querySelector('#bs-building-campus-filter');
  buildingCampusFilter?.querySelector('select').addEventListener('change', () => buildingCampusFilter.requestSubmit());

  if (window.BookingLoading) {
    filters.addEventListener('submit', event => {
      event.preventDefault();
      window.BookingLoading.navigate(() => filters.submit());
    });
  }

  const maintenance = page.querySelector('.bs-maintenance-charts');
  if (maintenance) {
    const campusButtons = maintenance.querySelectorAll('[data-maintenance-campus]');
    const views = maintenance.querySelectorAll('[data-maintenance-view]');
    for (const button of campusButtons) {
      button.addEventListener('click', () => {
        for (const choice of campusButtons) choice.setAttribute('aria-pressed', String(choice === button));
        for (const view of views) view.hidden = view.dataset.maintenanceView !== button.dataset.maintenanceCampus;
      });
    }
    for (const view of views) {
      const body = view.querySelector('tbody');
      if (!body) continue;
      const more = view.querySelector('[data-maintenance-more]');
      const headings = view.querySelectorAll('[data-maintenance-sort]');
      const original = [...body.rows];
      const statusOrder = ['Overdue', 'Ongoing', 'Upcoming', 'Completed', 'Catalog-only'];
      const collator = new Intl.Collator(undefined, {numeric: true});
      let rows = original;
      let sortKey = '';
      let direction = 1;
      let expanded = false;
      function updateRows() {
        rows.forEach((row, index) => { row.hidden = !expanded && index >= 10; });
        body.append(...rows);
      }
      for (const heading of headings) {
        heading.addEventListener('click', () => {
          const key = heading.dataset.maintenanceSort;
          direction = sortKey === key ? -direction : 1;
          sortKey = key;
          for (const column of headings) column.parentElement.removeAttribute('aria-sort');
          heading.parentElement.setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');
          rows = [...original].sort((first, second) => {
            const a = first.dataset[key];
            const b = second.dataset[key];
            if (key === 'start' && (!a || !b)) return Number(!a) - Number(!b);
            const difference = key === 'status' ? statusOrder.indexOf(a) - statusOrder.indexOf(b)
              : key === 'minutes' ? Number(a) - Number(b) : collator.compare(a, b);
            return difference * direction;
          });
          updateRows();
        });
      }
      more?.addEventListener('click', () => {
        expanded = !expanded;
        more.setAttribute('aria-expanded', String(expanded));
        more.textContent = expanded ? 'Show 10' : `View all ${original.length}`;
        updateRows();
      });
      const modes = view.querySelectorAll('[data-maintenance-mode]');
      const panels = view.querySelectorAll('[data-maintenance-panel]');
      for (const mode of modes) {
        mode.addEventListener('click', () => {
          for (const button of modes) button.setAttribute('aria-pressed', String(button === mode));
          for (const panel of panels) panel.hidden = panel.dataset.maintenancePanel !== mode.dataset.maintenanceMode;
        });
      }
    }
  }

  const chartTooltip = document.createElement('div');
  chartTooltip.className = 'bs-chart-tooltip';
  chartTooltip.hidden = true;
  chartTooltip.setAttribute('aria-hidden', 'true');
  document.body.append(chartTooltip);

  function positionTooltip(x, y) {
    const gap = 12;
    const viewport = document.documentElement;
    const {width, height} = chartTooltip.getBoundingClientRect();
    const left = x + gap + width <= viewport.clientWidth - gap ? x + gap : x - width - gap;
    const top = y + gap + height <= viewport.clientHeight - gap ? y + gap : y - height - gap;
    chartTooltip.style.left = `${Math.max(gap, left)}px`;
    chartTooltip.style.top = `${Math.max(gap, top)}px`;
  }

  function showTooltip(bar, x, y) {
    const parts = bar.dataset.chartDetails.split(' · ').map(part => part.trim()).filter(Boolean);
    const computed = getComputedStyle(bar);
    const accent = computed.getPropertyValue('--room-bar').trim()
      || computed.getPropertyValue('--maintenance-status').trim()
      || computed.getPropertyValue('--bs-accent').trim()
      || '#007367';
    const heading = document.createElement('strong');
    heading.className = 'bs-chart-tooltip-heading';
    heading.textContent = parts.shift() || bar.getAttribute('aria-label') || 'Chart details';
    const details = document.createElement('span');
    details.className = 'bs-chart-tooltip-details';
    details.textContent = parts.join('  ·  ');
    chartTooltip.replaceChildren(heading);
    if (parts.length) chartTooltip.append(details);
    chartTooltip.style.setProperty('--tooltip-accent', accent);
    chartTooltip.hidden = false;
    positionTooltip(x, y);
  }

  const hideTooltip = () => { chartTooltip.hidden = true; };
  page.addEventListener('pointerover', event => {
    const bar = event.target.closest('[data-chart-details]');
    if (bar && !bar.contains(event.relatedTarget)) showTooltip(bar, event.clientX, event.clientY);
  });
  page.addEventListener('pointermove', event => {
    if (!chartTooltip.hidden && event.target.closest('[data-chart-details]')) positionTooltip(event.clientX, event.clientY);
  });
  page.addEventListener('pointerout', event => {
    const bar = event.target.closest('[data-chart-details]');
    if (bar && !bar.contains(event.relatedTarget)) hideTooltip();
  });
  page.addEventListener('focusin', event => {
    const bar = event.target.closest('[data-chart-details]');
    if (!bar) return;
    const bounds = bar.getBoundingClientRect();
    showTooltip(bar, bounds.left + bounds.width / 2, bounds.bottom);
  });
  page.addEventListener('focusout', hideTooltip);
  page.addEventListener('keydown', event => { if (event.key === 'Escape') hideTooltip(); });
  window.addEventListener('scroll', hideTooltip, true);
  window.addEventListener('resize', hideTooltip);

  const roomChart = page.querySelector('.bs-room-chart');
  if (roomChart) {
    const panels = roomChart.querySelectorAll('[data-room-chart-kind]');
    const rooms = JSON.parse(roomChart.querySelector('#bs-room-chart-data').textContent);
    const percent = new Intl.NumberFormat(undefined, {maximumFractionDigits: 1});

    function renderRoomChart() {
      for (const panel of panels) {
        const kind = panel.dataset.roomChartKind;
        const ranked = kind === 'top' || kind === 'bottom';
        const direction = kind === 'bottom' ? 1 : -1;
        const eligible = rooms.filter(room => ranked ? room.rate !== null : String(room.timetable) === kind);
        eligible.sort((first, second) => {
          if (first.rate === null) return second.rate === null ? 0 : 1;
          if (second.rate === null) return -1;
          return direction * (first.rate - second.rate);
        });
        const visible = eligible.slice(0, 5);
        const status = panel.querySelector('[data-room-chart-status]');
        status.textContent = visible.length
          ? `Showing ${visible.length.toLocaleString()} of ${eligible.length.toLocaleString()} classrooms`
          : 'No classrooms in this category.';
        panel.querySelector('[data-room-chart-plot]').hidden = visible.length === 0;
        panel.querySelector('[data-room-chart-results]').replaceChildren(...visible.map(roomBar));
      }
    }

    function roomBar(room) {
      const item = document.createElement('li');
      const label = document.createElement('span');
      const number = document.createElement('strong');
      number.textContent = room.code || room.name;
      const location = document.createElement('small');
      location.textContent = [room.name !== number.textContent ? room.name : '', room.building, room.campus]
        .filter(Boolean).join(' · ');
      label.append(number, location);
      label.className = 'bs-vertical-label';
      const column = document.createElement('span');
      column.className = 'bs-vertical-column';
      column.style.setProperty('--bar-height', `${room.rate ?? 0}%`);
      const bar = document.createElement('span');
      bar.setAttribute('aria-hidden', 'true');
      const value = document.createElement('strong');
      value.textContent = room.rate === null ? 'Unavailable' : `${percent.format(room.rate)}%`;
      const timetable = room.timetable === null ? 'Timetable status unavailable'
        : room.timetable ? 'With timetable' : 'Without timetable';
      const utilization = room.rate === null ? 'Utilization unavailable' : `${value.textContent} utilization`;
      item.dataset.chartDetails = [number.textContent, location.textContent, utilization, timetable].filter(Boolean).join(' · ');
      item.setAttribute('aria-label', item.dataset.chartDetails);
      item.tabIndex = 0;
      column.append(value, bar);
      item.append(column, label);
      return item;
    }

    renderRoomChart();
  }

  const dialog = page.querySelector('#bs-kpi-dialog');
  function setupClassroomDirectory(directory) {
    const search = directory.querySelector('[data-classroom-search]');
    const campus = directory.querySelector('[data-classroom-campus]');
    const building = directory.querySelector('[data-classroom-building]');
    const classroom = directory.querySelector('[data-classroom-choice]');
    const status = directory.querySelector('[data-classroom-status]');
    const initialCampus = campus.value;
    const initialBuilding = directory.dataset.selectedBuilding;
    const rooms = [...directory.querySelectorAll('[data-classroom-key]')].map(row => ({
      row, ...row.dataset, searchText: row.dataset.roomSearch.toLowerCase().replace(/\s+/g, ' '),
    }));
    const buildingRows = directory.querySelectorAll('[data-utilization-building]');
    const matchesCampus = room => !campus.value || room.campus === campus.value;
    const matchesLocation = room => matchesCampus(room) && (!building.value || room.building === building.value);

    function filterRooms() {
      const words = search.value.toLowerCase().trim().split(/\s+/);
      let matches = 0;
      for (const room of rooms) {
        const visible = matchesLocation(room)
          && (!classroom.value || room.classroomKey === classroom.value)
          && words.every(word => room.searchText.includes(word));
        room.row.hidden = !visible;
        if (visible) matches++;
      }
      for (const row of buildingRows) {
        row.hidden = !building.value || !matchesLocation(row.dataset);
      }
      status.textContent = matches
        ? `${matches.toLocaleString()} classroom${matches === 1 ? '' : 's'} found`
        : 'No classrooms match.';
    }

    function updateClassroomOptions() {
      const selected = classroom.value;
      classroom.replaceChildren(new Option('All classrooms', ''));
      for (const room of rooms) {
        if (matchesLocation(room)) {
          classroom.add(new Option(room.roomLabel, room.classroomKey));
          if (room.classroomKey === selected) classroom.value = selected;
        }
      }
      filterRooms();
    }

    function updateBuildingOptions(selected = building.value) {
      const names = [...new Set(rooms.filter(matchesCampus).map(room => room.building))]
        .sort((first, second) => first.localeCompare(second));
      building.replaceChildren(new Option('All buildings', ''), ...names.map(name => new Option(name, name)));
      if (names.includes(selected)) building.value = selected;
      updateClassroomOptions();
    }

    campus.addEventListener('change', () => updateBuildingOptions());
    building.addEventListener('change', updateClassroomOptions);
    classroom.addEventListener('change', filterRooms);
    search.addEventListener('input', filterRooms);
    directory.querySelector('[data-classroom-clear]').addEventListener('click', () => {
      search.value = '';
      campus.value = initialCampus;
      classroom.value = '';
      updateBuildingOptions(initialBuilding);
      search.focus();
    });
    updateBuildingOptions(initialBuilding);
  }

  if (dialog) {
    const title = dialog.querySelector('#bs-kpi-dialog-title');
    const content = dialog.querySelector('#bs-kpi-dialog-content');
    page.querySelectorAll('[data-kpi-details]').forEach(card => {
      card.addEventListener('click', () => {
        const details = document.getElementById(card.dataset.kpiDetails);
        title.textContent = details.dataset.title;
        content.replaceChildren(details.content.cloneNode(true));
        dialog.querySelector('#bs-dialog-download-error').hidden = true;
        dialog.showModal();

        const classroomDirectory = content.querySelector('[data-classroom-directory]');
        if (classroomDirectory) {
          setupClassroomDirectory(classroomDirectory);
          return;
        }
        const directory = content.querySelector('[data-campus-directory]');
        if (!directory) return;
        const search = directory.querySelector('[data-building-search]');
        const status = directory.querySelector('[data-building-status]');
        const choices = [...directory.querySelectorAll('[data-campus-choice]')];
        const sections = [...directory.querySelectorAll('[data-campus-buildings]')];
        let selected = choices.find(choice => choice.dataset.campusChoice.toLowerCase()
          === directory.dataset.selectedCampus.toLowerCase())?.dataset.campusChoice || '';
        function updateBuildings() {
          const query = search.value.trim().toLowerCase();
          let matches = 0;
          for (const choice of choices) {
            choice.setAttribute('aria-pressed', String(choice.dataset.campusChoice === selected));
          }
          for (const section of sections) {
            const inScope = selected ? section.dataset.campusBuildings === selected : Boolean(query);
            let visible = 0;
            if (inScope) {
              for (const row of section.querySelectorAll('[data-building-name]')) {
                row.hidden = !row.dataset.buildingName.toLowerCase().includes(query);
                if (!row.hidden) visible++;
              }
            }
            section.hidden = !inScope || (!visible && !selected);
            matches += visible;
          }
          status.textContent = selected || query
            ? (matches ? `${matches} building${matches === 1 ? '' : 's'} found` : 'No buildings match your search.')
            : 'Select a campus to see its buildings.';
        }
        for (const choice of choices) {
          choice.addEventListener('click', () => {
            const campusName = choice.dataset.campusChoice;
            selected = selected === campusName ? '' : campusName;
            updateBuildings();
          });
        }
        search.addEventListener('input', updateBuildings);
        updateBuildings();
      });
    });
  }

  if (window.BookingLoading) {
    page.addEventListener('click', async event => {
      const download = event.target.closest?.('a[download="booking-analytics.xlsx"]');
      if (!download || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const error = page.querySelector(download.closest('dialog') ? '#bs-dialog-download-error' : '#bs-download-error');
      error.hidden = true;
      try {
        const file = await window.BookingLoading.run(async () => {
          const response = await fetch(download.href);
          if (!response.ok || !response.headers.get('Content-Type')?.includes('spreadsheetml.sheet')) {
            throw new Error('Excel download failed');
          }
          return response.blob();
        });
        const url = URL.createObjectURL(file);
        const link = document.createElement('a');
        link.href = url;
        link.download = download.download;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch {
        error.hidden = false;
      }
    });
  }
})();
