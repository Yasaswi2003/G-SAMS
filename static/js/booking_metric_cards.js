/* Interactive metric cards, scoped to Booking Analytics. */
window.BookingMetricCards = {
  previous: {},
  showDataPoint(title, rows, ui) {
    const dialog=document.getElementById('ba-metric-dialog');
    dialog.querySelector('h2').textContent=title;
    dialog.querySelector('p').textContent='Details for the selected chart data.';
    const content=dialog.querySelector('#ba-metric-content');content.replaceChildren();
    const list=ui.el('dl','bm-comparison');
    rows.forEach(([label,value])=>{const pair=ui.el('div','');pair.append(ui.el('dt','',label),ui.el('dd','',String(value)));list.append(pair);});
    content.append(list);
    if(!dialog.open)dialog.showModal();
  },
  render(data, ui) {
    const {el, svg, cards} = ui;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const number = new Intl.NumberFormat(undefined, {maximumFractionDigits: 1});
    const icons = ['bx-calendar-check', 'bx-check-shield', 'bx-timer', 'bx-time-five'];
    const dateLabel = value => new Date(value + 'T00:00:00').toLocaleDateString(undefined, {day:'numeric', month:'short'});
    const display = (value, index) => value === null || !Number.isFinite(value) ? '—' :
      (index === 0 ? number.format(Math.round(value)) : number.format(value) + (index === 1 ? '%' : ' days'));
    const spark = (container, card, index, large = false, onPick = null) => {
      const hourly = Boolean(card.hourly);
      const values = hourly ? card.hourly : card.series;
      const valid = values.filter(value => value !== null);
      const area = el('div', 'bm-spark-wrap' + (large ? ' bm-spark-large' : ''));
      if (!valid.length) {
        area.append(el('span', 'bm-no-trend', 'No decided bookings in this period'));
        container.append(area);
        return;
      }
      const width = 320, height = large ? 115 : 58, floor = height - 4;
      const max = Math.max(...valid, 1), min = Math.min(...valid, 0);
      const plot = svg('svg', {viewBox:`0 0 ${width} ${height}`, class:'bm-spark-svg', role:'img',
        'aria-label':card.label + (hourly ? ' by hour' : ' over selected dates')});
      const points = values.map((value, i) => ({x:values.length === 1 ? width / 2 : i / (values.length - 1) * width,
        y:floor - ((value ?? 0) - min) / (max - min || 1) * (height - 12), value}));
      if (hourly) {
        values.forEach((value, i) => plot.append(svg('rect', {x:i * width / values.length + 3,
          y:floor - value / max * (height - 12), width:width / values.length - 6,
          height:Math.max(1, value / max * (height - 12)), rx:3,
          fill:value === max && value > 0 ? '#ecffbd' : '#b9f1d980'})));
      } else {
        // Keep gaps where no rate/lead-time observations exist.
        let segment = [];
        const draw = () => {
          if (!segment.length) return;
          const path = segment.map((point, i) => (i ? 'L' : 'M') + point.x + ',' + point.y).join(' ');
          plot.append(svg('path', {d:path + ` L ${segment.at(-1).x},${floor} L ${segment[0].x},${floor} Z`, fill:'#c5ffe629'}),
            svg('path', {d:path, fill:'none', stroke:'#c7ffe4', 'stroke-width':2, 'stroke-linejoin':'round'}));
          if (segment.length === 1) plot.append(svg('circle', {cx:segment[0].x,cy:segment[0].y,r:3,fill:'#d7ffdc'}));
          segment = [];
        };
        points.forEach(point => {if (point.value === null) draw(); else segment.push(point);});
        draw();
      }
      const guide = svg('line', {y1:2,y2:floor,stroke:'#fff9','stroke-dasharray':'3 3',opacity:0});
      const marker = svg('circle', {r:4,fill:'#fff',stroke:'#00786f','stroke-width':2,opacity:0});
      const readout = el('span','bm-readout'); readout.hidden = true;
      let selected = 0;
      const select = indexValue => {
        selected = Math.max(0,Math.min(values.length-1,indexValue));
        const point = points[selected];
        guide.setAttribute('x1',point.x);guide.setAttribute('x2',point.x);guide.setAttribute('opacity',1);
        marker.setAttribute('cx',point.x);marker.setAttribute('cy',point.y);marker.setAttribute('opacity',point.value === null ? 0 : 1);
        const label = hourly ? (8+selected)+':00' : dateLabel(data.dashboard.trend[selected]?.label || data.start);
        readout.textContent = label + ' · ' + (hourly ? number.format(point.value)+' booked minutes' : display(point.value,index));
        readout.hidden = false;
      };
      plot.append(guide,marker);
      const overlay = svg('rect', {x:0,y:0,width,height,fill:'transparent',tabindex:0,
        role:'slider','aria-label':card.label+' trend; use left and right arrows',
        'aria-valuemin':0,'aria-valuemax':Math.max(0,values.length-1),'aria-valuenow':0});
      const update = value => {select(value);overlay.setAttribute('aria-valuenow',selected);overlay.setAttribute('aria-valuetext',readout.textContent);};
      overlay.addEventListener('pointermove',event=>{const rect=plot.getBoundingClientRect();update(Math.round((event.clientX-rect.left)/rect.width*(values.length-1)));});
      overlay.addEventListener('focus',()=>update(selected));
      overlay.addEventListener('click',event=>{event.stopPropagation();const rect=plot.getBoundingClientRect();update(Math.round((event.clientX-rect.left)/rect.width*(values.length-1)));onPick?.(selected);});
      overlay.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();event.stopPropagation();update(event.key==='Home'?0:event.key==='End'?values.length-1:selected+(event.key==='ArrowLeft'?-1:1));if(large)onPick?.(selected);}else if(event.key==='Enter'){event.preventDefault();event.stopPropagation();onPick?.(selected);}});
      const hide=()=>{guide.setAttribute('opacity',0);marker.setAttribute('opacity',0);readout.hidden=true;};
      overlay.addEventListener('pointerleave',hide);overlay.addEventListener('blur',hide);
      plot.append(overlay);area.append(plot,readout);container.append(area);
    };
    cards.replaceChildren();
    data.dashboard.cards.forEach((card,index)=>{
      const key=card.label, value=card.numeric_value ?? (index===0 ? Number(card.value) : parseFloat(card.value));
      const old=this.previous[key];
      const changed=Number.isFinite(value)&&old!==undefined&&old!==value;
      const box=el('article','ba-card bd-card bm-card'+(changed?' bm-changed':''));
      const head=el('div','bm-head'),icon=el('span','bm-icon');icon.append(el('i','bx '+icons[index]));
      head.append(el('span','ba-card-label',card.label),icon);
      const row=el('div','bd-value-row'),valueNode=el('strong','',typeof card.value==='number'?number.format(card.value):card.value);
      row.append(valueNode);
      if(card.delta!==null){
        const positive=index===2?card.delta<=0:card.delta>=0;
        const badge=el('span','bd-delta '+(positive?'bd-positive':'bd-negative'),
          (card.delta>0?'↗ ':card.delta<0?'↘ ':'→ ')+number.format(Math.abs(card.delta))+'%');
        badge.title='Relative change versus preceding equal-length period';row.append(badge);
      }
      box.append(head,row,el('small','bd-card-note',card.note));
      spark(box,card,index,false,selected=>openDetails(selected));
      const footer=el('div','bm-footer');
      const baseline=index===3?'Confirmed bookings only':card.previous_value===null||card.previous_value===undefined?'No prior baseline':'Previous: '+display(card.previous_value,index);
      footer.append(el('span','bm-baseline',baseline));
      const details=el('button','bm-details','Explore ↗');details.type='button';
      details.setAttribute('aria-label','Explore '+card.label);
      const openDetails=(selected=null)=>{
        const dialog=document.getElementById('ba-metric-dialog');
        dialog.querySelector('h2').textContent=card.label;
        dialog.querySelector('p').textContent=card.note;
        const content=dialog.querySelector('#ba-metric-content');content.replaceChildren();
        const comparison=el('dl','bm-comparison');
        for(const [label,text] of [['Selected period',dateLabel(data.start)+' – '+dateLabel(data.end)],
          ['Current value',typeof card.value==='number'?number.format(card.value):card.value],
          ['Previous period',dateLabel(data.dashboard.previous_start)+' – '+dateLabel(data.dashboard.previous_end)],
          ['Previous value',index===3?'Not compared':display(card.previous_value??null,index)],
          ['Relative change',card.delta===null?'No comparable baseline':number.format(card.delta)+'%']]){
          const pair=el('div','');pair.append(el('dt','',label),el('dd','',text));comparison.append(pair);
        }
        content.append(comparison);
        const selection=el('div','bm-selected-data');selection.setAttribute('aria-live','polite');
        const values=card.hourly||card.series;
        const updateSelection=position=>{
          const label=card.hourly?(8+position)+':00':dateLabel(data.dashboard.trend[position]?.label||data.start);
          const value=values[position];
          selection.replaceChildren(el('span','','Selected '+(card.hourly?'hour':'date')+': '+label),
            el('strong','',card.hourly?number.format(value)+' confirmed minutes':display(value,index)));
        };
        if(values.length)updateSelection(selected??Math.max(0,values.findLastIndex(value=>value!==null)));
        const chart=el('div','bm-dialog-chart');spark(chart,card,index,true,updateSelection);
        content.append(chart,selection,el('p','bm-chart-help','Click the chart to inspect a value, or focus it and use the arrow keys.'));
        if(!dialog.open)dialog.showModal();
      };
      details.addEventListener('click',()=>openDetails());
      box.tabIndex=0;box.setAttribute('aria-label',card.label+'. Select to explore metric details.');
      box.addEventListener('click',event=>{if(!event.target.closest('button,svg'))openDetails();});
      box.addEventListener('keydown',event=>{if(event.target===box&&(event.key==='Enter'||event.key===' ')){event.preventDefault();openDetails();}});
      footer.append(details);box.append(footer);cards.append(box);
      if(index<3&&Number.isFinite(value)&&!reducedMotion&&(old===undefined||changed)){
        const begin=performance.now(),from=Number.isFinite(old)?old:0;
        const animate=now=>{if(!valueNode.isConnected)return;const progress=Math.min(1,(now-begin)/700);
          valueNode.textContent=display(from+(value-from)*(1-Math.pow(1-progress,3)),index);
          if(progress<1)requestAnimationFrame(animate);else valueNode.textContent=typeof card.value==='number'?number.format(card.value):card.value;};
        requestAnimationFrame(animate);
      }
      this.previous[key]=value;
      if(!reducedMotion){box.addEventListener('pointermove',event=>{const rect=box.getBoundingClientRect();box.style.setProperty('--pointer-x',(event.clientX-rect.left)+'px');box.style.setProperty('--pointer-y',(event.clientY-rect.top)+'px');});}
    });
  }
};
