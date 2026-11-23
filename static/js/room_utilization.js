(() => {
    const page = document.getElementById('room-utilization');
    const get = name => document.getElementById('ru-' + name);
    const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
    const hours = Array.from({length: 9}, (_, index) => index + 8);
    const filters = Object.fromEntries(['term', 'campus', 'building', 'room', 'day'].map(name => [name, get(name)]));
    const formatter = new Intl.NumberFormat(undefined, {maximumFractionDigits: 1});
    const format = value => formatter.format(value);
    const share = (used, total) => total ? used / total * 100 : 0;
    const percent = (used, total) => format(share(used, total)) + '%';
    const time = hour => String(hour).padStart(2, '0') + ':00';
    const interval = hour => time(hour) + '–' + time(hour + 1);
    const buildingKey = room => room.buildingKey;
    const ordered = values => [...new Set(values)].sort((a, b) => a.localeCompare(b, undefined, {numeric: true}));
    const add = (parent, tag, text, className) => {
        const element = document.createElement(tag);
        if (text != null) element.textContent = text;
        if (className) element.className = className;
        parent.append(element);
        return element;
    };
    const pageSize = 50;
    let rooms, terms, currentRooms, tablePage = 0;

    function options(select, entries, all) {
        const oldValue = select.value;
        const choices = entries.map(([value, label]) => new Option(label, value));
        if (all) choices.unshift(new Option(all, ''));
        select.replaceChildren(...choices);
        if (choices.some(option => option.value === oldValue)) select.value = oldValue;
    }

    function cascade() {
        const campus = filters.campus.value;
        const available = rooms.filter(room => !campus || room.campus === campus);
        const buildings = new Map(available.map(room => [buildingKey(room), room]));
        options(filters.building, [...buildings].sort(([, a], [, b]) => a.building.localeCompare(b.building, undefined, {numeric: true}))
            .map(([key, room]) => [key, campus ? room.building : room.building + ' · ' + room.campus]), 'All buildings');
        const building = filters.building.value;
        const order = [...available].sort((a, b) => a.name.localeCompare(b.name, undefined, {numeric: true}));
        options(filters.room, order.filter(room => !building || buildingKey(room) === building)
            .map(room => [String(room.index), [room.name, room.name !== room.code ? room.code : '', !building ? room.building : '']
                .filter(Boolean).join(' · ')]), 'All rooms');
    }

    function focusScope(room, singleRoom) {
        filters.campus.value = room.campus;
        cascade();
        filters.building.value = buildingKey(room);
        cascade();
        filters.room.value = singleRoom ? String(room.index) : '';
        get('search').value = '';
        update();
        (singleRoom ? filters.room : filters.building).focus();
    }

    function plot(id, labels, counts, capacity, axis) {
        const chart = get(id);
        chart.replaceChildren();
        const roughStep = Math.max(1, (Math.max(...counts) + 1) / 4);
        const magnitude = 10 ** Math.floor(Math.log10(roughStep));
        const step = [1, 2, 2.5, 5, 10].map(value => value * magnitude)
            .find(value => value >= roughStep && Number.isInteger(value));
        const maximum = step * 4;
        const plot = add(chart, 'div', null, 'ru-plot');
        plot.style.setProperty('--plot-width', labels.length * 39 + 72 + 'px');
        add(plot, 'span', 'Class hours', 'ru-y-title');
        const ticks = add(add(plot, 'div', null, 'ru-axis'), 'div', null, 'ru-axis-scale');
        for (let tick = maximum; tick >= 0; tick -= step) add(ticks, 'span', format(tick));
        const columns = add(plot, 'div', null, 'ru-columns');
        for (const [index, label] of labels.entries()) {
            const column = add(columns, 'div', null, 'ru-column');
            const box = add(column, 'div', null, 'ru-column-plot');
            const bar = add(box, 'div', null, 'ru-bar');
            const detail = label + ' · ' + format(counts[index]) + ' class hours · ' + percent(counts[index], capacity) + ' of room time in use';
            bar.style.setProperty('--height', share(counts[index], maximum) + '%');
            bar.classList.toggle('ru-bar-empty', counts[index] === 0);
            bar.title = detail;
            bar.tabIndex = 0;
            bar.setAttribute('role', 'img');
            bar.setAttribute('aria-label', detail);
            add(bar, 'strong', format(counts[index]));
            add(column, 'span', label);
        }
        add(chart, 'p', axis, 'ru-axis-title');
    }

    function insights(selectedDays, dayCounts, hourCounts, unused) {
        const list = get('insights');
        list.replaceChildren();
        if (!currentRooms.length) {
            add(list, 'li', 'No active rooms match these filters.');
            return;
        }
        add(list, 'li', format(unused) + ' of ' + format(currentRooms.length) + ' rooms had no classes.');
        if (!currentRooms[0].used) {
            add(list, 'li', 'No classes were scheduled in these rooms during the selected days.');
            return;
        }
        const describe = (labels, counts, unit) => {
            if (counts.length === 1) return;
            const high = Math.max(...counts);
            const low = Math.min(...counts);
            if (high === low) {
                add(list, 'li', 'Every ' + unit + ' had ' + format(high) + ' class hours.');
                return;
            }
            for (const [name, value] of [['Busiest', high], ['Quietest', low]]) {
                const matches = labels.filter((_, index) => counts[index] === value);
                const label = matches.length > 2 ? matches[0] + ' and ' + (matches.length - 1) + ' others tied' : matches.join(' and ');
                add(list, 'li', name + ' ' + unit + ' — ' + label + ' (' +
                    format(value) + (value === 1 ? ' class hour' : ' class hours') + (matches.length > 1 ? ' each).' : ').'));
            }
        };
        describe(selectedDays.map(index => days[index]), dayCounts, 'day');
        describe(hours.map(interval), hourCounts, 'hour');
        const busiest = currentRooms[0];
        const tied = currentRooms.filter(room => room.used === busiest.used).length;
        add(list, 'li', busiest.name + ' (' + busiest.building + ') ' +
            (tied > 1 ? 'tied with ' + (tied - 1) + ' other ' + (tied === 2 ? 'room' : 'rooms') + ' for the most use' : 'was the busiest room') +
            ' with ' + format(busiest.used) + ' class hours.');
    }

    function track(parent, value) {
        add(add(parent, 'div', null, 'ru-track'), 'span').style.setProperty('--width', value + '%');
    }

    function breakdown(available) {
        const buildingList = get('buildings');
        const bands = get('bands');
        buildingList.replaceChildren();
        bands.replaceChildren();
        const buildings = new Map();
        const usageBands = [0, 0, 0, 0];
        for (const room of currentRooms) {
            const key = buildingKey(room);
            if (!buildings.has(key)) buildings.set(key, {room, used: 0, unused: 0, count: 0});
            const building = buildings.get(key);
            building.used += room.used;
            building.unused += Number(!room.used);
            building.count++;
            const used = Math.round(share(room.used, available));
            usageBands[!room.used ? 0 : used <= 25 ? 1 : used <= 60 ? 2 : 3]++;
        }
        if (!buildings.size) add(buildingList, 'p', 'No buildings match these filters.');
        for (const {room, used, unused, count} of [...buildings.values()].sort((a, b) => b.used - a.used)) {
            const building = add(buildingList, 'button', null, 'ru-building');
            building.type = 'button';
            add(building, 'strong', room.building + ' · ' + room.campus);
            const details = add(building, 'small', format(used) + ' h · ' + format(count) + ' rooms · ' + format(unused) + ' unused · ');
            add(details, 'strong', percent(used, count * available));
            track(building, share(used, count * available));
            building.addEventListener('click', () => focusScope(room, false));
        }
        ['Not used', 'Low (1–25%)', 'Medium (26–60%)', 'High (61%+)'].forEach((label, index) => {
            const band = add(bands, 'div', null, 'ru-band');
            add(band, 'span', label);
            track(band, share(usageBands[index], currentRooms.length));
            add(band, 'strong', format(usageBands[index]));
        });
    }

    function heatmap(selectedDays, grid) {
        const host = get('heatmap');
        host.replaceChildren();
        const table = add(host, 'table', null, 'ru-heatmap');
        table.setAttribute('aria-label', 'Number of rooms in use by day and hour');
        const header = add(add(table, 'thead'), 'tr');
        for (const label of ['Day', ...hours.map(time)]) add(header, 'th', label).scope = 'col';
        const body = add(table, 'tbody');
        selectedDays.forEach((day, index) => {
            const row = add(body, 'tr');
            add(row, 'th', days[day].slice(0, 3)).scope = 'row';
            grid[index].forEach((count, hourIndex) => {
                const rate = share(count, currentRooms.length);
                const cell = add(row, 'td', currentRooms.length ? format(count) : '—', rate >= 55 ? 'ru-hot' : null);
                cell.style.setProperty('--heat', rate);
                cell.title = days[day] + ' ' + interval(hours[hourIndex]) + ' · ' + format(count) + ' of ' +
                    format(currentRooms.length) + ' rooms in use';
                cell.tabIndex = 0;
            });
        });
    }

    function renderTable() {
        const body = get('table');
        body.replaceChildren();
        const query = get('search').value.trim().toLowerCase();
        const matches = currentRooms.filter(room => [room.name, room.code, room.building, room.campus, room.type]
            .some(value => value.toLowerCase().includes(query)));
        const start = tablePage * pageSize;
        for (const room of matches.slice(start, start + pageSize)) {
            const row = add(body, 'tr');
            const open = add(add(row, 'td'), 'button', room.name, 'ru-table-room');
            open.type = 'button';
            open.addEventListener('click', () => focusScope(room, true));
            for (const value of [room.building + ' · ' + room.campus, room.type, format(room.used), percent(room.used, room.available)]) {
                add(row, 'td', value);
            }
        }
        if (!matches.length) add(add(body, 'tr'), 'td', 'No rooms match your search.').colSpan = 5;
        get('count').textContent = matches.length
            ? 'Showing ' + format(start + 1) + '–' + format(Math.min(matches.length, start + pageSize)) + ' of ' + format(matches.length)
            : '0 rooms';
        get('prev').disabled = tablePage === 0;
        get('next').disabled = start + pageSize >= matches.length;
    }

    function update() {
        const {campus, building, room, day, term} = filters;
        const selectedDays = day.value === '' ? days.map((_, index) => index) : [Number(day.value)];
        const available = selectedDays.length * hours.length;
        const grid = selectedDays.map(() => hours.map(() => 0));
        const masks = terms[term.value];
        currentRooms = rooms.filter(item => (!campus.value || item.campus === campus.value)
            && (!building.value || buildingKey(item) === building.value)
            && (room.value === '' || item.index === Number(room.value))).map(item => {
            const mask = masks[item.index] || 0;
            let used = 0;
            // Decode safely in 9-bit blocks. JavaScript bitwise operators truncate at 32 bits.
            selectedDays.forEach((dayIndex, index) => {
                const block = Math.floor(mask / 512 ** dayIndex) % 512;
                hours.forEach((_, hourIndex) => {
                    const occupied = (block >> hourIndex) & 1;
                    used += occupied;
                    grid[index][hourIndex] += occupied;
                });
            });
            return {...item, used, available};
        }).sort((a, b) => b.used - a.used || a.name.localeCompare(b.name, undefined, {numeric: true}));
        const dayCounts = grid.map(row => row.reduce((sum, value) => sum + value, 0));
        const hourCounts = hours.map((_, index) => grid.reduce((sum, row) => sum + row[index], 0));
        const used = dayCounts.reduce((sum, value) => sum + value, 0);
        const unused = currentRooms.filter(item => !item.used).length;
        const count = currentRooms.length;
        get('rate').textContent = count ? percent(used, count * available) : '—';
        get('hours-label').textContent = day.value === '' ? 'Class hours per week' : 'Class hours on ' + days[Number(day.value)];
        get('hours').textContent = format(used);
        get('rooms').textContent = format(count);
        get('unused').textContent = format(unused);
        insights(selectedDays, dayCounts, hourCounts, unused);
        plot('by-day', selectedDays.map(index => days[index].slice(0, 3)), dayCounts, count * hours.length, 'Day of week');
        plot('by-hour', hours.map(time), hourCounts, count * selectedDays.length, 'Hour starting at');
        breakdown(available);
        heatmap(selectedDays, grid);
        tablePage = 0;
        renderTable();
    }

    async function initialize() {
        const status = get('status');
        try {
            const data = await BookingLoading.run(async () => {
                const response = await fetch(page.dataset.url);
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error);
                return payload;
            });
            if (data.version !== 1 || !Object.keys(data.terms).length) throw new Error('The timetable file has no usable terms.');
            terms = data.terms;
            rooms = data.rooms.map(([name, campus, building, type, , code, key], index) =>
                ({name, campus, building, type, code, index, buildingKey: key || JSON.stringify([campus, building])}));
            const termOrder = term => term.replace(/#ODD$/i, '#1').replace(/#EVEN$/i, '#2');
            const termNames = Object.keys(terms).sort((a, b) => termOrder(b).localeCompare(termOrder(a), undefined, {numeric: true}));
            options(filters.term, termNames.map(term => [term, term.replace('#', ' · ')]));
            options(filters.campus, ordered(rooms.map(room => room.campus)).map(campus => [campus, campus]), 'All campuses');
            options(filters.day, days.map((day, index) => [String(index), day]), 'All weekdays');
            cascade();
            Object.values(filters).forEach(select => select.addEventListener('change', () => {
                if (select === filters.campus || select === filters.building) cascade();
                update();
            }));
            get('reset').addEventListener('click', () => {
                filters.term.selectedIndex = 0;
                for (const name of ['campus', 'building', 'room', 'day']) filters[name].value = '';
                get('search').value = '';
                cascade();
                update();
            });
            get('search').addEventListener('input', () => { tablePage = 0; renderTable(); });
            get('prev').addEventListener('click', () => { tablePage--; renderTable(); });
            get('next').addEventListener('click', () => { tablePage++; renderTable(); });
            update();
            status.hidden = true;
            page.querySelector('.ru-content').hidden = false;
        } catch (error) {
            status.textContent = error.message || 'Timetable data could not be loaded. Refresh to try again.';
        }
    }

    initialize();
})();
