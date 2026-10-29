// Allowlisted adapter for the installed official KuGou PC client's own bridge.
// No cookies, user tokens or raw network signatures leave this page context.
(() => {
  if (window.__kugouNativeMcp?.version === 3) return true;
  if (typeof external.SuperCall !== 'function') throw Error('KuGou native bridge unavailable');
  const candidates = new Map();
  let daily = null;
  const clean = s => String(s || '').replace(/<[^>]+>/g, '');
  const call = (cmd, args = {}) => new Promise((resolve, reject) => {
    const name = '__kgMcp_' + Math.random().toString(36).slice(2);
    const finish = (error, value) => {
      clearTimeout(timer); delete window[name];
      error ? reject(error) : resolve(value);
    };
    const timer = setTimeout(() => finish(Error('Native callback timed out: ' + cmd)), 8000);
    window[name] = v => {
      try { finish(null, typeof v === 'string' ? JSON.parse(v) : v); }
      catch (e) { finish(e); }
    };
    try { external.SuperCall(cmd, JSON.stringify({...args, callback:name})); }
    catch (e) { finish(e); }
  });
  const status = async () => {
    const s = await call(864);
    let source = null;
    try { source = JSON.parse(s.QueueSource || '{}').WebInfo; } catch (_) {}
    return {available:String(s.status)==='1', title:s.filename || '', hash:s.hash || '',
      mixsongid:s.mix_song_id || '', playback:s.play_status || 'stopped',
      duration_ms:Number(s.duration || 0), source:source?.type || '',
      source_name:source?.info?.name || ''};
  };
  const summary = (s, index) => ({index:index+1, title:clean(s.songname || s.audio_name),
    artist:clean(s.author_name || s.singername), album:clean(s.album_name),
    mixsongid:String(s.mixsongid || s.album_audio_id || ''), hash:s.hash,
    duration_ms:Number(s.duration || Number(s.time_length || 0)*1000)});
  const file = (s, source) => ({filename:clean(s.filename || `${s.author_name} - ${s.songname}`)+'.mp3',
    hash:s.hash, size:String(s.filesize || s.file_size || 0),
    duration:String(s.duration || Number(s.time_length || 0)*1000),
    bitrate:String(s.bitrate || 128), encrypt:'-1', mvhash:s.mv_hash || '',
    mvtrack:s.music_trac || 0, isfilehead:s.is_file_head || 0,
    privilege:String(s.privilege || 0), isvip:s.trans_param?.musicpack_advance===1?1:0,
    album_id:String(s.album_id || 0), songname:clean(s.songname || s.audio_name),
    mixsongid:String(s.mixsongid || s.album_audio_id || 0), scid:String(s.scid || 0),
    album_name:clean(s.album_name), quality:String(s.quality || 0),
    vip_icon:s.trans_param?.musicpack_advance===1?'1':'0',
    singerinfo:s.singerinfo?.map(a=>({singerid:String(a.id || 0),singername:a.name})) ||
      s.Singers?.map(a=>({singerid:String(a.id || a.ID || 0),singername:a.name || a.Name})) ||
      [{singerid:'0',singername:clean(s.author_name || s.singername)}],
    song_source:source, tracker_info:s.tracker_info});
  const play = async (songs, index, source, name, path, options = {}) => {
    if (!songs.length || !Number.isInteger(index) || index<0 || index>=songs.length)
      throw Error('Invalid queue/index');
    const expected = songs[index];
    external.SuperCall(45, JSON.stringify({Source:'0', SourceFile:options.sourceFile ?? source, SourcePath:source,
      op_source:options.opSource ?? name, ChargePath:'', ClassName:'', Files:options.files ?? songs.map(s=>file(s,source)),
      QueueInfo:{Play:'1', PlayAll:songs.length>1?'1':'0', Clear:'1',Force:'1',
        IsMV:'0',Insert:'0',Index:String(index),AddToDefaultList:'0'},
      QueueSource:{type:name,info:options.info ?? {name,path,tabId:'commonWeb'}}}));
    let actual = null;
    for (let attempt=0;attempt<35;attempt++) {
      await new Promise(r=>setTimeout(r,300));
      actual=await status();
      if (actual.playback==='playing' && (!options.verifySource || actual.source_name===name) &&
          (actual.mixsongid===String(expected.mixsongid || expected.album_audio_id) ||
          actual.hash.toLowerCase()===String(expected.hash).toLowerCase()))
        return {verified:true, submitted_count:songs.length, queue_contents_verified:false,
          start_index:index+1, actual};
    }
    throw Error('Playback not verified; actual=' + JSON.stringify(actual));
  };
  const getDaily = async () => {
    const r=await call(984);
    if (String(r.status)!=='1' || !Array.isArray(r.data?.song_list) || !r.data.song_list.length)
      throw Error('Daily recommendations unavailable from current client account');
    daily={songs:r.data.song_list,expires:Date.now()+300000,date:r.data.creation_date};
    return {date:daily.date,count:daily.songs.length,source:'官方PC客户端每日推荐',
      songs:daily.songs.map(summary)};
  };
  const favoriteCollection = async name => {
    // Resolve the collection freshly on every call: no hardcoded account/list IDs
    // and no cached contents that could survive an account change.
    const lists=await call(681);
    if(String(lists.status)!=='1' || !Array.isArray(lists.data))
      throw Error('无法读取收藏歌单，请确认酷狗已登录并加载收藏');
    const matches=lists.data.filter(l=>l.listname===name);
    if(matches.length!==1)
      throw Error(matches.length?'收藏歌单名称重复，请使用唯一名称':'未找到收藏歌单：'+name);
    const list=matches[0], encoded=BigInt(list.listId);
    if((encoded>>32n)!==1n)throw Error('所选列表不是已验证的云收藏类型');
    const id=String(encoded&0xffffffffn);
    const response=await call(872,{listid:id,listtype:'cloud_list'});
    if(String(response.status)!=='1' || !Array.isArray(response.data))
      throw Error('无法读取收藏歌曲：'+name);
    return {name:list.listname,id,songs:response.data};
  };
  const favoriteSummary = (s,index) => {
    const filename=clean(s.titlename || s.filename?.replace(/\.[^.]+$/,''));
    const separator=filename.indexOf(' - ');
    return {index:index+1,title:separator<0?filename:filename.slice(separator+3),
      artist:separator<0?'':filename.slice(0,separator),hash:s.hash,
      album_id:s.album_id || '',duration_ms:Number(s.duration || 0)};
  };
  const search = async (keyword, limit) => {
    const frame=document.createElement('iframe');
    frame.style.cssText='position:fixed;left:-20000px;top:0;width:1100px;height:800px;visibility:hidden';
    frame.setAttribute('aria-hidden','true');
    frame.src='https://pc.service.kugou.com/search/2024/static/html/index.html?keyword='+encodeURIComponent(keyword);
    document.body.append(frame);
    try {
      let songs=null;
      for(let i=0;i<90;i++) {
        await new Promise(r=>setTimeout(r,200));
        try {
          const w=frame.contentWindow.document.querySelector('#iframe_complex')?.contentWindow;
          const found=w?.mindb?.query('songDataDB',true);
          if(Array.isArray(found) && found.length){songs=found;break;}
          if(w?.document?.body.innerText.includes('没有找到')) break;
        } catch (_) {}
      }
      if(!songs) throw Error('Online search did not return verified results within 18 seconds');
      const now=Date.now();
      for(const [key,v] of candidates) if(v.expires<now)candidates.delete(key);
      if(candidates.size>300)candidates.clear();
      const result=songs.slice(0,limit).map((s,i)=>{
        const result_id=String(s.mixsongid)+'_'+String(s.hash).toLowerCase();
        candidates.set(result_id,{song:s,expires:now+600000,keyword});
        return {...summary(s,i),result_id};
      });
      return {scope:'online',keyword,returned:result.length,available_in_page:songs.length,
        source:'官方PC客户端综合搜索',songs:result};
    } finally {frame.remove();}
  };
  window.__kugouNativeMcp={version:3,status,getDaily,search,
    getFavorites:async (name,offset,limit)=>{
      const collection=await favoriteCollection(name);
      return {collection:collection.name,count:collection.songs.length,offset,
        returned:collection.songs.slice(offset,offset+limit).length,
        has_more:offset+limit<collection.songs.length,
        songs:collection.songs.slice(offset,offset+limit).map((s,i)=>favoriteSummary(s,offset+i))};
    },
    playFavorites:async (name,index)=>{
      const collection=await favoriteCollection(name);
      if(!collection.songs.length)throw Error('收藏歌单为空：'+name);
      const result=await play(collection.songs,index,'我的收藏\\'+collection.name,
        collection.name,'',{files:collection.songs,sourceFile:collection.name,opSource:'我的收藏',verifySource:true,
          info:{name:collection.name,listid:collection.id,listtype:'cloud_list',path:''}});
      return {collection:collection.name,count:collection.songs.length,...result};
    },
    playDaily:async index=>{
      if(!daily || daily.expires<Date.now())await getDaily();
      return play(daily.songs,index,'为你推荐\\金刚区\\每日推荐','每日推荐',
        'https://pc.service.kugou.com/yueku/2024/find/index.html#/daily');
    },
    playSearch:async id=>{
      const c=candidates.get(id);
      if(!c || c.expires<Date.now())throw Error('Search result expired; search again');
      return play([c.song],0,'搜索结果\\综合单曲搜索\\关键字搜索\\'+c.keyword,'搜索',
        'https://pc.service.kugou.com/search/2024/static/html/index.html?keyword='+encodeURIComponent(c.keyword));
    },
    control:async action=>{
      external.SuperCall(841,JSON.stringify({status:action}));
      await new Promise(r=>setTimeout(r,500));
      const actual=await status();
      if((action==='pause' && actual.playback!=='paused' && actual.playback!=='pasued') ||
         (action==='play' && actual.playback!=='playing'))throw Error('Playback control not verified');
      return {verified:true,actual};
    }
  };
  return true;
})()
